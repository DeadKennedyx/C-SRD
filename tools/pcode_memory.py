"""Ordered byte/word buffer reconstruction from binary-only high P-code.

The public signature supplies types, not memory footprints or algorithm facts.
Parameter-relative pointers remain symbolic, so emitted C retains all alias
relationships. Every load is snapshotted at its instruction position; stores
are never pruned just because the returned value does not depend on them.
"""
from dataclasses import dataclass
import re

from pcode_values import Builder, Unsupported, Value, literal, SCALAR, COMPARE
from pcode_cfg import LIMITS, index


@dataclass(frozen=True)
class Pointer:
    bits: int
    slot: int
    offset: int | Value = 0  # byte offset modulo pointer width


@dataclass(frozen=True)
class CodePointer:
    bits: int
    slot: int  # Opaque code identity, never a data address or scalar.


@dataclass(frozen=True)
class StreamPointer:
    bits: int
    slot: int  # Opaque FILE identity; no FILE layout or buffer access.


TYPES = {"uint32": "unsigned int", "uint32-buffer": "unsigned int",
         "unsigned-char-buffer": "unsigned char", "signed-char-buffer": "signed char", "char-buffer": "char"}
ALLOCATORS = {"malloc", "calloc", "realloc", "free"}
STDIO_ABI = {name: {'returns': 'void' if name=='clearerr' else 'int32',
                   'parameters': [{'kind':kind,'read_only':False} for kind in kinds]}
             for name,kinds in {'fgetc':['file-stream'],'fputc':['int32','file-stream'],
                               'fflush':['file-stream'],'feof':['file-stream'],
                               'ferror':['file-stream'],'clearerr':['file-stream']}.items()}


def has_scalar_call_argument(export):
    # Mutating a recursive rank can introduce nontermination/stack exhaustion;
    # use return/memory controls for self-calls, not an unsafe execution control.
    direct=any(p['kind'] in ('uint32','int32') for op in export['operations'] if op['opcode']=='CALL' and op.get('callee')!=export['function']
               for p in export.get('call_signatures',{}).get(op.get('callee'),{}).get('parameters',[]))
    indirect=any(op['opcode']=='CALLIND' for op in export['operations']) and any(
        p['kind']=='uint32' for target in export['parameters'] if target['kind']=='function-pointer'
        for p in target['parameters'])
    return direct or indirect


def reconstruct(export, *, metrics=None, result_offset=0, store_offset=0, final_store_offset=0, call_argument_offset=0):
    try:
        return _reconstruct(export, {} if metrics is None else metrics, result_offset, store_offset, final_store_offset, call_argument_offset)
    except Unsupported:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise Unsupported(f"malformed memory P-code: {error}") from error


def _reconstruct(export, metrics, result_offset, store_offset, final_store_offset, call_argument_offset):
    stdio=(export.get('schema_version'),export.get('memory_model'))==(10,'ordered-stdio-buffers-v1')
    guarded=stdio or (export.get('schema_version'),export.get('memory_model'))==(9,'guarded-calls-buffers-v2')
    records = guarded or (export.get("schema_version") == 8 and export.get("memory_model") == "records-state-buffers-v1")
    calls = records or (export.get("schema_version") == 7 and export.get("memory_model") == "ordered-calls-buffers-v1")
    extended = calls or (export.get("schema_version") == 5 and export.get("memory_model") == "ordered-byte-buffers-v2")
    if not extended and (export.get("schema_version") != 4 or export.get("memory_model") != "ordered-u32-buffers-v1"):
        raise Unsupported("requires ordered buffer export schema 4 or 5")
    heap = extended and any(o.get('opcode')=='CALL' and o.get('callee') in ALLOCATORS for o in export.get('operations',[]))
    calls = calls or heap
    name, arity, parameters = export["function"], export["arity"], export["parameters"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise Unsupported("invalid function symbol")
    if type(arity) is not int or not 1 <= arity <= 8 or len(parameters) != arity:
        raise Unsupported("invalid public buffer interface")
    for p in parameters:
        allowed=set(TYPES)|({'record-buffer'} if records else set())|({'function-pointer'} if guarded and not stdio else set())|({'file-stream'} if stdio else set())
        if p["kind"] not in (allowed if extended else ("uint32", "uint32-buffer")) or type(p["read_only"]) is not bool:
            raise Unsupported("invalid parameter kind or constness")
        if p["kind"] in ("uint32","file-stream") and p["read_only"]:
            raise Unsupported("const scalar parameters are outside the contract")
    if not calls and not any(p["kind"] != "uint32" for p in parameters):
        raise Unsupported("buffer observer requires at least one pointer")
    signatures = export.get("call_signatures", {}) if calls else {}
    if not isinstance(signatures,dict) or len(signatures)>64:raise Unsupported("invalid call signatures")
    if stdio and (heap or any(STDIO_ABI.get(k)!=v for k,v in signatures.items())):
        raise Unsupported('stdio observation requires exact standard library ABIs')
    declarations=['#include <stdio.h>'] if stdio else ['#include <stdlib.h>'] if heap else []
    record_types={}
    def symbol(name):
        return isinstance(name,str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",name) and not re.fullmatch(r"[pv][0-9]+",name)
    def call_types(spec):
        if spec['returns'] not in (('void','uint32','int32') if stdio else ('void','uint32')) or not isinstance(spec['parameters'],list) or len(spec['parameters'])>8:
            raise Unsupported('invalid call ABI')
        result=[]
        for p in spec['parameters']:
            if stdio and p['kind'] in ('int32','file-stream') and p['read_only'] is False:
                result.append('int' if p['kind']=='int32' else 'FILE*');continue
            if p['kind'] not in TYPES or type(p['read_only']) is not bool or (p['kind']=='uint32' and p['read_only']):
                raise Unsupported('invalid call parameter type')
            result.append(('const ' if p['read_only'] else '')+TYPES[p['kind']]+('*' if p['kind']!='uint32' else ''))
        return ','.join(result) or 'void'
    code_names=set()
    for p in parameters:
        if p['kind']=='function-pointer':
            if not symbol(p.get('name')) or p['name']==name or p['name'] in code_names or p['read_only']:
                raise Unsupported('invalid or conflicting callback parameter name')
            code_names.add(p['name']);call_types(p)
    def parameter_name(i):return parameters[i]['name'] if parameters[i]['kind']=='function-pointer' else f'p{i}'
    def record_type(p):
        r=p["record"]
        if not symbol(r["tag"]) or type(r["union"]) is not bool or r["alignment"]!=4 or not 1<=len(r["fields"])<=16:
            raise Unsupported("unsupported public record layout")
        fields=sorted(r["fields"],key=lambda f:(f["byte_offset"],f["name"]))
        if len({f["name"] for f in fields})!=len(fields) or r["bytes"]!=(4 if r["union"] else 4*len(fields)):
            raise Unsupported("padded or duplicate record layout")
        for i,f in enumerate(fields):
            if not symbol(f["name"]) or f["kind"]!="uint32" or f["byte_offset"]!=(0 if r["union"] else 4*i):
                raise Unsupported("invalid public record field")
        if r["tag"] in record_types and record_types[r["tag"]]!=r:raise Unsupported("conflicting record definitions")
        if r["tag"] not in record_types:
            declarations.append(("union " if r["union"] else "struct ")+r["tag"]+" {"+"".join("unsigned int "+f["name"]+";" for f in fields)+"};")
            record_types[r["tag"]]=r
        return ("union " if r["union"] else "struct ")+r["tag"]
    def ctype(p):return 'FILE' if p['kind']=='file-stream' else record_type(p) if p["kind"]=="record-buffer" else TYPES[p["kind"]]
    for p in parameters:
        if p["kind"]=="record-buffer":record_type(p)
    objects=list(parameters)
    globals_=export.get("persistent_objects",[]) if records else []
    addresses=[]
    global_slots={}
    for g in globals_:
        if not symbol(g["name"]) or g["name"]==name or any(g["name"]==p.get("name") for p in objects):
            raise Unsupported("invalid or duplicate global symbol")
        if g["kind"] not in ("uint32-buffer","record-buffer"):raise Unsupported("unsupported persistent type")
        slot=len(objects);objects.append({**g,"read_only":False,"persistent":True})
        global_slots[g["name"]]=slot
        declarations.append("extern "+ctype(g)+" "+g["name"]+";")
        start=int(g["address"]);size=g.get("record",{}).get("bytes",4)
        if any(start<b and a<start+size for a,b,_ in addresses):raise Unsupported("overlapping global symbols")
        addresses.append((start,start+size,slot))
    for callee,spec in signatures.items():
        if (not isinstance(callee,str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",callee) or
            re.fullmatch(r"[pv][0-9]+",callee) or callee in code_names or (callee==name and not guarded)):
            raise Unsupported("invalid or conflicting external call symbol")
        types=call_types(spec)
        if not stdio:declarations.append(("void" if spec["returns"]=="void" else "unsigned int")+" "+callee+"("+types+");")
    space = export["address_space"]
    if type(space["pointer_bytes"]) is not int or space["pointer_bytes"] not in (4, 8) or space["addressable_unit_bytes"] != 1:
        raise Unsupported("requires byte-addressed 32/64-bit pointers")
    if type(space["id"]) is not int or not 0 <= space["id"] <= 0xffffffff:
        raise Unsupported("invalid memory space identifier")
    pointer_bits = space["pointer_bytes"] * 8
    nodes, ops, blocks = export["nodes"], export["operations"], export["blocks"]
    if not all(isinstance(v, list) for v in (nodes, ops, blocks)):
        raise Unsupported("invalid graph lists")
    if len(nodes) > LIMITS["nodes"] or len(ops) > LIMITS["operations"]:
        raise Unsupported("P-code budget exceeded")
    diamonds=0
    graph=None
    if export.get("operation_order") != "basic-block-live-order":
        raise Unsupported("requires ordered basic-block instructions")
    if extended:
        from pcode_memory_cfg import linearize,validated_graph
        if heap:
            graph=validated_graph(export,heap=True)
            if any(o['opcode']=='CALL' and o.get('callee') not in ALLOCATORS for o in ops):
                raise Unsupported('heap observation excludes opaque or unknown calls')
        else:
            try:
                linear,diamonds=linearize(export)
                if stdio and diamonds:
                    # Optimizers can merge FILE parameters after a branch.
                    # Keep each incoming identity on its own CFG path rather
                    # than passing opaque handles to the scalar select builder.
                    graph=validated_graph(export);diamonds=0
                else:ops=linear
            except Unsupported:
                if not records:raise
                graph=validated_graph(export)
                if not guarded and any(o['opcode']=='CALL' for o in ops):raise Unsupported('conditional calls are not modeled')
        if graph is None:blocks=[{"id":0,"incoming":[],"outgoing":[],"operations":list(range(len(ops)))}]
    if graph is None and len(blocks) != 1:
        raise Unsupported("buffer observer currently requires one ordered basic block")
    block = blocks[0]
    if graph is None and (type(block["id"]) is not int or (not extended and export["entry_block"] != block["id"]) or
            block["incoming"] or block["outgoing"] or block["operations"] != list(range(len(ops)))):
        raise Unsupported("inconsistent straight-line block membership")
    if graph is None and (not ops or ops[-1]["opcode"] != "RETURN" or any(o["opcode"] == "RETURN" for o in ops[:-1])):
        raise Unsupported("requires one final return")
    metrics.update(observer="ordered-calls-buffers-v1" if calls else "ordered-byte-buffers-v2" if extended else "ordered-u32-buffers-v1", evaluated_operations=0,
                   emitted_statements=0, loads=0, stores=0, public_stores=0, pointer_operations=0,
                   calls=0,
                   scalar_diamonds=diamonds,
                   footprint_elements={str(i): 0 for i, p in enumerate(objects) if p["kind"] not in ('uint32','function-pointer','file-stream')})
    if guarded:metrics['observer']='guarded-calls-buffers-v2'
    if stdio:metrics['observer']='ordered-stdio-buffers-v1'
    class ScopedBuilder(Builder):
        def emit(self,bits,expression):
            value=super().emit(bits,expression)
            if graph is not None:self.lines.append('    (void)'+value.atom+';')
            return value
    builder, values, definitions = ScopedBuilder(metrics), {}, set()
    bounds, predicates, multiples, origins = {}, {}, {}, {}
    identical_scalars = {}
    lower,excluded={},{}
    constant_choices={};choice_depth={}
    linear_forms={}

    def multiple(value):
        if value.known is not None:return (value.known & -value.known) if value.known else (1<<value.bits)
        return multiples.get(value,1)

    def bound(value):
        if value.known is not None: return value.known
        maximum=bounds.get(value,(1<<value.bits)-1)
        if value in linear_forms:
            constant,terms=linear_forms[value]
            upper=constant+sum(coefficient*bound(term) for term,coefficient in terms.items())
            if upper < (1<<value.bits):maximum=min(maximum,upper)
        if value in bounds:return maximum
        if value.parts: return sum(bound(part) << (i*32) for i,part in enumerate(value.parts))
        return maximum

    def minimum(value,depth=0):
        if value.known is not None:return value.known
        result=lower.get(value,0)
        if value in linear_forms:
            constant,terms=linear_forms[value]
            upper=constant+sum(coefficient*bound(term) for term,coefficient in terms.items())
            if upper < (1<<value.bits):
                result=max(result,constant+sum(coefficient*minimum(term,depth+1) for term,coefficient in terms.items()))
        if depth<32 and value in origins:
            code,bits,args=origins[value];a=minimum(args[0],depth+1);mask=(1<<bits)-1
            if code in ('COPY','CAST','INT_ZEXT') and bound(args[0])<=mask:result=max(result,a)
            elif code in ('INT_ADD','INT_MULT'):
                b=minimum(args[1],depth+1);maximum=bound(args[0])+bound(args[1]) if code=='INT_ADD' else bound(args[0])*bound(args[1])
                if maximum<=mask:result=max(result,a+b if code=='INT_ADD' else a*b)
        return result

    def comparison(code,a,b):
        lo,hi,other_lo,other_hi=minimum(a),bound(a),minimum(b),bound(b)
        if code=='INT_LESS':
            if hi<other_lo:return True
            if lo>=other_hi:return False
        if code=='INT_LESSEQUAL':
            if hi<=other_lo:return True
            if lo>other_hi:return False
        if code in ('INT_EQUAL','INT_NOTEQUAL'):
            if hi<other_lo or other_hi<lo:return code=='INT_NOTEQUAL'
            if lo==hi==other_lo==other_hi:return code=='INT_EQUAL'
        return None

    def comparison_operands(code,args):
        if code not in ('INT_EQUAL','INT_NOTEQUAL') or len(args)!=2 or any(a.bits!=32 for a in args):return args
        # Cancel common affine terms on both sides, modulo 2^32. A compiler
        # may count from 3*x to 3*x+(x&3); the shared offset does not change
        # equality, even when either side wraps. No range/seed hints are used.
        constant=0;terms={}
        for a,weight in zip(args,(1,-1)):
            c,t=(a.known,{}) if a.known is not None else linear_forms.get(a,(0,{a:1}))
            constant=(constant+weight*c)&0xffffffff
            for term,coefficient in t.items():terms[term]=(terms.get(term,0)+weight*coefficient)&0xffffffff
        terms={term:coefficient for term,coefficient in terms.items() if coefficient}
        if not terms:return [literal(32,constant),literal(32,0)]
        if len(terms)==1:
            term,coefficient=next(iter(terms.items()))
            if coefficient&1:
                # Only odd coefficients are invertible over all BV32 values.
                inverse=pow(coefficient,-1,1<<32)
                normalized=literal(32,(-constant*inverse)&0xffffffff)
                metrics['invertible_comparison_normalizations']=metrics.get('invertible_comparison_normalizations',0)+1
                return [term,normalized]
        return args

    def operation(code, bits, args):
        # Some high-P-code exports narrow a masked temporary without resizing
        # its inputs, or retain a wider comparison constant. Normalize only
        # when no possible value loses a bit; raw scalar shape checks stay strict.
        if (records or heap) and code=='INT_AND' and len(args)==2 and args[0].bits==args[1].bits and bits<args[0].bits<=32:
            if any(a.known is not None and a.known < (1<<bits) for a in args):
                metrics['lossless_width_normalizations']=metrics.get('lossless_width_normalizations',0)+1
                full=operation(code,args[0].bits,args)
                return operation('SUBPIECE',bits,[full,literal(32,0)])
        if (records or heap) and code in COMPARE and bits==8 and len(args)==2 and args[0].bits!=args[1].bits:
            small,wide=sorted(args,key=lambda a:a.bits)
            if wide.known is not None and wide.known < (1<<small.bits):
                metrics['lossless_width_normalizations']=metrics.get('lossless_width_normalizations',0)+1
                args=[literal(small.bits,a.known) if a==wide else a for a in args]
        if code=='INT_MULT' and bits==32 and all(a.bits==32 and a.known is None for a in args) and len(args)==2:
            for factor,other in (args,list(reversed(args))):
                if factor in constant_choices:
                    condition,yes,no=constant_choices[factor]
                    metrics['selected_constant_multiplications']=metrics.get('selected_constant_multiplications',0)+1
                    return select(condition,operation(code,bits,[other,yes]),operation(code,bits,[other,no]))
            small,other=sorted(args,key=bound)
            maximum=bound(small)
            if maximum<=16:
                # Binary compilers can turn a choice of constant scales into a
                # variable multiply. Reconstruct its proved small unsigned range
                # using exact bit selection, without admitting general C multiply.
                metrics['bounded_multiplications']=metrics.get('bounded_multiplications',0)+1
                result=literal(32,0)
                for bit in range(maximum.bit_length()):
                    flag=operation('INT_AND',32,[small,literal(32,1<<bit)])
                    flag=operation('INT_NOTEQUAL',8,[flag,literal(32,0)])
                    scaled=operation('INT_MULT',32,[other,literal(32,1<<bit)])
                    result=operation('INT_ADD',32,[result,select(flag,scaled,literal(32,0))])
                return result
        value = builder.operation(code, bits, args)
        if bits==32 and all(a.bits==32 for a in args) and value.known is None and value not in args:
            # Exact unsigned affine normalization for range analysis. This is
            # algebra over Z/(2^32), not recognition of an encoder or its seed.
            # Infer a conventional interval only when the normalized sum cannot
            # wrap; otherwise retain the full bit-vector range.
            def form(a):return (a.known,{}) if a.known is not None else linear_forms.get(a,(0,{a:1}))
            weights=None
            if code in ('COPY','CAST'):weights=[1]
            elif code in ('INT_ADD','INT_SUB'):weights=[1,1 if code=='INT_ADD' else -1]
            elif code=='INT_MULT' and any(a.known is not None for a in args):
                fixed=0 if args[0].known is not None else 1
                weights=[0,0];weights[1-fixed]=args[fixed].known
            if weights is not None:
                constant=0;terms={};mask=0xffffffff
                for a,weight in zip(args,weights):
                    c,t=form(a);constant=(constant+weight*c)&mask
                    for term,coefficient in t.items():terms[term]=(terms.get(term,0)+weight*coefficient)&mask
                terms={term:coefficient for term,coefficient in terms.items() if coefficient}
                if len(terms)<=16:linear_forms[value]=(constant,terms)
        if graph is not None and code in COMPARE:
            analysis_args=comparison_operands(code,args)
            known=comparison(code,*analysis_args)
            if known is not None:return literal(bits,int(known))
        maximum = (1 << bits)-1
        a, b = bound(args[0]), bound(args[1]) if len(args)>1 else 0
        if code in ("COPY", "CAST", "INT_ZEXT"): maximum = min(maximum,a)
        elif code == "INT_SEXT" and a < (1 << (args[0].bits-1)): maximum = a
        elif code == "INT_ADD" and a+b <= maximum: maximum = a+b
        elif code == "INT_SUB" and minimum(args[0])>=b: maximum = a-minimum(args[1])
        elif code == "INT_MULT" and a*b <= maximum: maximum = a*b
        elif code == "INT_AND": maximum = min(a,b)
        elif code in ("INT_OR","INT_XOR"): maximum = (1 << max(a,b).bit_length())-1
        elif code in COMPARE or code == "BOOL_NEGATE": maximum = 1
        elif code == "INT_LEFT" and args[1].known is not None:
            shift=args[1].known
            if shift>=bits: maximum=0
            elif a<<shift <= maximum: maximum=a<<shift
        elif code in ("INT_RIGHT","SUBPIECE") and args[1].known is not None:
            maximum=min(maximum,a >> (args[1].known*(8 if code=="SUBPIECE" else 1)))
        bounds[value]=maximum
        m=1
        if code in ("COPY","CAST","INT_ZEXT","INT_SEXT"):m=multiple(args[0])
        elif code=="INT_MULT":m=multiple(args[0])*multiple(args[1])
        elif code in ("INT_ADD","INT_SUB","INT_OR","INT_XOR"):m=min(multiple(args[0]),multiple(args[1]))
        elif code=="INT_AND":m=max(multiple(args[0]),multiple(args[1]))
        elif code=="INT_LEFT" and args[1].known is not None:m=multiple(args[0])<<min(args[1].known,bits)
        multiples[value]=min(1<<bits,m)
        if value.known is None and value not in args:
            signature=(code,bits,tuple(args));origins[value]=signature
            peers=identical_scalars.setdefault(signature,set())
            for peer in peers:
                if peer in bounds:bounds[value]=min(bounds[value],bounds[peer])
                if peer in lower:lower[value]=max(lower.get(value,0),lower[peer])
                if peer in excluded:excluded.setdefault(value,set()).update(excluded[peer])
            peers.add(value)
        if value.known is None:
            if code in COMPARE:
                analyzed=comparison_operands(code,args)
                predicates[value]=(code,*analyzed,False)
            elif code=="BOOL_NEGATE" and args[0] in predicates:
                code,a,b,negated=predicates[args[0]];predicates[value]=(code,a,b,not negated)
        return value

    def select(condition,yes,no):
        if condition.bits!=8 or yes.bits!=no.bits:raise Unsupported("invalid scalar diamond values")
        if condition.known is not None:return yes if condition.known else no
        if yes.bits>32:
            if len(yes.parts)!=len(no.parts):raise Unsupported("inconsistent wide scalar merge")
            result=Value(yes.bits,"",parts=tuple(select(condition,a,b) for a,b in zip(yes.parts,no.parts)))
        else:result=builder.emit(yes.bits,f"({condition.atom} ? {yes.atom} : {no.atom})")
        cache={}
        def branch_bound(value,truth,depth=0):
            key=(value,truth)
            if key in cache:return cache[key]
            maximum=bound(value)
            if condition in predicates:
                code,a,b,negated=predicates[condition];holds=truth!=negated
                if code in ("INT_LESS","INT_LESSEQUAL"):
                    if value==a and b.known is not None and holds:
                        maximum=min(maximum,max(0,b.known-(code=="INT_LESS")))
                    if value==b and a.known is not None and not holds:
                        maximum=min(maximum,max(0,a.known-(code=="INT_LESSEQUAL")))
            # A compiler may move widening/scaling into a branch before its
            # phi. Propagate the condition through those total operations.
            # Depth exhaustion only loses precision; it never invents a bound.
            if value in origins and depth<64:
                code,bits,args=origins[value];mask=(1<<bits)-1
                a=branch_bound(args[0],truth,depth+1)
                b=branch_bound(args[1],truth,depth+1) if len(args)>1 else 0
                inferred=mask
                if code in ("COPY","CAST","INT_ZEXT"):inferred=min(mask,a)
                elif code=="INT_SEXT" and a<(1<<(args[0].bits-1)):inferred=a
                elif code=="INT_AND":inferred=min(a,b)
                elif code=="INT_ADD" and a+b<=mask:inferred=a+b
                elif code=="INT_MULT" and a*b<=mask:inferred=a*b
                elif code in ("INT_LEFT","INT_RIGHT","SUBPIECE") and args[1].known is not None:
                    shift=args[1].known*(8 if code=="SUBPIECE" else 1)
                    if shift>=args[0].bits:inferred=0
                    elif code!="INT_LEFT":inferred=a>>shift
                    elif a<<shift<=mask:inferred=a<<shift
                maximum=min(maximum,inferred)
            cache[key]=maximum
            return maximum
        bounds[result]=max(branch_bound(yes,True),branch_bound(no,False))
        multiples[result]=min(multiple(yes),multiple(no))
        if yes.bits==32 and all(v.known is not None or v in constant_choices for v in (yes,no)):
            depth=1+max(choice_depth.get(v,0) for v in (yes,no))
            if depth<=32:constant_choices[result]=(condition,yes,no);choice_depth[result]=depth
        return result
    for i, node in enumerate(nodes):
        size = node["size"]
        if type(size) is not int or size not in (1, 2, 4, 8):
            raise Unsupported("unsupported storage width")
        if "constant" in node:
            number = node["constant"]
            if ("parameter" in node or node.get("input") or not isinstance(number, str) or
                    not number.isascii() or not number.isdecimal() or len(number) > 20):
                raise Unsupported("invalid constant or input flags")
            values[i] = literal(size * 8, int(number))
        elif "parameter" in node:
            slot = index(node["parameter"], arity, "parameter")
            pointer = parameters[slot]["kind"] != "uint32"
            if node.get("input") is not True or size != (space["pointer_bytes"] if pointer else 4):
                raise Unsupported("parameter storage disagrees with public ABI")
            values[i] = StreamPointer(pointer_bits,slot) if parameters[slot]['kind']=='file-stream' else CodePointer(pointer_bits,slot) if parameters[slot]['kind']=='function-pointer' else Pointer(pointer_bits, slot) if pointer else Value(32, f"p{slot}")
        elif records and node.get("input") and "linkage_pointer" in node:
            if size*8!=pointer_bits or node["linkage_pointer"] not in global_slots:
                raise Unsupported("invalid linkage pointer input")
            values[i]=Pointer(pointer_bits,global_slots[node["linkage_pointer"]])

    def read(i):
        if i not in values:
            raise Unsupported("unresolved input or definition used before its instruction")
        return values[i]

    def constant(value):
        if not isinstance(value, Value) or value.known is None:
            raise Unsupported("requires a constant pointer offset/stride")
        return value.known

    def address(pointer, bits=32, write=False, argument=False):
        if records and isinstance(pointer,Value) and pointer.known is not None:
            for start,end,slot in addresses:
                if start<=pointer.known<end:
                    pointer=Pointer(pointer_bits,slot,pointer.known-start);break
        if not isinstance(pointer, Pointer) or pointer.bits != pointer_bits:
            raise Unsupported("memory address is not derived from a public pointer")
        obj=objects[pointer.slot]
        if obj["kind"]=="record-buffer":
            if bits!=32 or argument:raise Unsupported("record observer requires uint32 field accesses")
            r=obj["record"];stride=r["bytes"];offset=pointer.offset
            field_offset=offset%stride if isinstance(offset,int) else None
            if not isinstance(offset,int):
                def residue(value,depth=0):
                    if value.known is not None:return value.known%stride
                    if multiple(value)%stride==0:return 0
                    if depth>64 or value not in origins:return None
                    op,_,args=origins[value]
                    if op in ("COPY","CAST","INT_ZEXT"):return residue(args[0],depth+1)
                    if op in ("INT_ADD","INT_MULT"):
                        a,b=(residue(v,depth+1) for v in args)
                        if a is not None and b is not None:return (a+b if op=="INT_ADD" else a*b)%stride
                    return None
                # Power-of-two strides divide pointer modulus. Otherwise a
                # modular expression's residue is not justified by this rule.
                if stride&(stride-1):raise Unsupported("dynamic record stride must be a power of two")
                field_offset=residue(offset)
                maximum=bound(offset)//stride
                if field_offset is None or maximum>255:raise Unsupported("unbounded or unresolved dynamic record field")
                low=offset.parts[0] if offset.parts else offset
                element=operation("INT_RIGHT",32,[low,literal(32,stride.bit_length()-1)])
                captured=builder.emit(32,element.atom)
                expression=f"({captured.atom} <= {maximum}u ? {captured.atom} : {maximum}u)"
            else:
                if offset<0 or offset//stride>255:raise Unsupported("record index outside bounded domain")
                maximum=offset//stride;expression=str(maximum)
            fields=[f for f in r["fields"] if f["byte_offset"]==field_offset]
            if not fields:raise Unsupported("address does not identify a record field")
            if obj["read_only"] and write:raise Unsupported("store through const record")
            if obj.get("persistent") and maximum:raise Unsupported("global record overrun")
            metrics["footprint_elements"][str(pointer.slot)]=max(metrics["footprint_elements"][str(pointer.slot)],maximum+1)
            return (obj["name"] if obj.get("persistent") else f"p{pointer.slot}[{expression}]")+"."+fields[0]["name"]
        element_bytes = 4 if obj["kind"] == "uint32-buffer" else 1
        if bits != element_bytes*8: raise Unsupported("memory access width differs from public pointee type")
        if isinstance(pointer.offset,int):
            if pointer.offset % element_bytes or not 0 <= pointer.offset <= (255 if extended else 15)*element_bytes:
                raise Unsupported("unaligned or out-of-contract fixed memory offset")
            element = pointer.offset // element_bytes
            expression = str(element)
        else:
            maximum=bound(pointer.offset)
            if maximum>255*element_bytes or multiple(pointer.offset)<element_bytes:
                raise Unsupported("dynamic observer offset must be bounded and element-aligned")
            low=pointer.offset.parts[0] if pointer.offset.parts else pointer.offset
            if element_bytes==4:low=operation("INT_RIGHT",32,[low,literal(32,2)]);maximum//=4
            # Abstract interval reasoning proves this clamp is a no-op in the
            # P-code. Source grading checks it independently before crediting it.
            captured=builder.emit(32,low.atom)
            element=maximum
            expression=f"({captured.atom} <= {maximum}u ? {captured.atom} : {maximum}u)"
        if write and obj["read_only"]:
            raise Unsupported("store through a read-only public parameter")
        footprint = metrics["footprint_elements"]
        footprint[str(pointer.slot)] = max(footprint[str(pointer.slot)], element + 1)
        if obj.get("persistent"):
            if pointer.offset!=0:raise Unsupported("global scalar overrun")
            return "(&"+obj["name"]+")" if argument else obj["name"]
        base=obj['heap_name'] if obj.get('heap_name') else f"p{pointer.slot}"
        if argument:return base if isinstance(pointer.offset,int) and pointer.offset==0 else f"({base}+{expression})"
        return f"{base}[{expression}]"

    def heap_base(pointer):
        if isinstance(pointer,Value) and pointer.bits==pointer_bits and pointer.known==0:return '0'
        if not isinstance(pointer,Pointer) or not objects[pointer.slot].get('heap_name') or pointer.offset!=0:
            raise Unsupported('allocator requires a captured owned base or null')
        return objects[pointer.slot]['heap_name']

    def allocation_size(value, *, bytes):
        if not isinstance(value,Value) or value.bits!=pointer_bits:
            raise Unsupported('allocator size does not match size_t ABI')
        maximum=32*(4 if bytes else 1)
        if bound(value)>maximum or (bytes and multiple(value)<4):
            raise Unsupported('allocator extent is not bounded to 32 aligned words')
        if value.known is not None:return str(value.known)+'u'
        low=value.parts[0] if value.parts else value
        if bytes:low=operation('INT_RIGHT',32,[low,literal(32,2)])
        count=builder.emit(32,low.atom)
        upper=bound(value)//(4 if bytes else 1)
        clamped=f'({count.atom} <= {upper}u ? {count.atom} : {upper}u)'
        return clamped+('*sizeof(unsigned int)' if bytes else '')

    def heap_binding(expression):
        slot=len(objects);name=f'csrd_observed_heap_{slot}'
        if name in signatures or name==export['function'] or any(o.get('name')==name for o in objects):
            raise Unsupported('generated heap handle conflicts with a public symbol')
        objects.append({'kind':'uint32-buffer','read_only':False,'heap_name':name})
        metrics['footprint_elements'][str(slot)]=0
        builder.lines.append(f'    unsigned int *{name} = {expression};')
        return Pointer(pointer_bits,slot)

    result = None
    path_public_store = None
    final_store = max((i for i, op in enumerate(ops) if op["opcode"] == "STORE"), default=-1) if final_store_offset else -1
    def process(oi,op):
        nonlocal result,call_argument_offset,path_public_store
        code, inputs = op["opcode"], op["inputs"]
        if (graph is None and op.get("block") != block["id"]) or not isinstance(inputs, list):
            raise Unsupported("invalid instruction block or inputs")
        for i in inputs:
            index(i, len(nodes), "varnode")
        out = op.get("output")
        if out is not None:
            index(out, len(nodes), "varnode")
            if (graph is None and (out in values or out in definitions)) or nodes[out].get("input") or 'constant' in nodes[out]:
                raise Unsupported("multiple definitions or overwriting input/constant")
            definitions.add(out)
        if code in ("STORE", "RETURN"):
            if out is not None or len(inputs) != (3 if code == "STORE" else 2):
                raise Unsupported("invalid store/return interface")
        elif out is None and not (calls and code in ('CALL','CALLIND')):
            raise Unsupported("missing data instruction output")
        bits = nodes[out]["size"] * 8 if out is not None else None
        # Return input 0 is an instruction address, not a value computation.
        args = [read(i) for i in inputs[1:]] if code in ("RETURN","CALL","CALLIND") else [read(i) for i in inputs]
        if code == "RETURN":
            result = args[0]
            if not isinstance(result, Value) or result.bits != 32:
                raise Unsupported("return must be uint32")
            if graph is not None:
                if (heap or guarded) and final_store_offset and path_public_store is not None:
                    # Corrupt the final public write on this executed path.
                    # A lexically last store can belong to an unreachable arm;
                    # a last private-heap store can be discarded by free.
                    destination,value=path_public_store
                    builder.lines.append(f'    {destination} = ({value} + {final_store_offset & 0xffffffff}u);')
                expression=result.atom if not result_offset else f'({result.atom}+{result_offset & 0xffffffff}u)'
                builder.lines.append('    return '+expression+';')
        elif records and code=="INDIRECT":
            # Only loader-resolved GOT slots are immutable in this observer's
            # ordinary C object model. Never discard an INDIRECT on program data.
            if len(args)!=2 or not isinstance(args[0],Pointer) or out is None:
                raise Unsupported("unmodeled INDIRECT effect")
            object_name=objects[args[0].slot].get("name")
            if (not object_name or nodes[out].get("linkage_pointer")!=object_name or
                nodes[inputs[0]].get("linkage_pointer")!=object_name or args[0].offset!=0):
                raise Unsupported("INDIRECT is not an unchanged loader linkage slot")
            values[out]=args[0]
        elif heap and code=='CALL':
            callee=op.get('callee');arity=2 if callee in ('calloc','realloc') else 1
            if callee not in ALLOCATORS or len(args)!=arity or not inputs:
                raise Unsupported('unknown allocator or mismatched allocator arity')
            if (callee=='free' and out is not None) or (callee!='free' and (out is None or bits!=pointer_bits)):
                raise Unsupported('allocator return storage disagrees with the ABI')
            if callee=='free':arguments=[heap_base(args[0])]
            elif callee=='realloc':arguments=[heap_base(args[0]),allocation_size(args[1],bytes=True)]
            elif callee=='malloc':arguments=[allocation_size(args[0],bytes=True)]
            else:
                widths=[i for i,a in enumerate(args) if isinstance(a,Value) and a.bits==pointer_bits and a.known==4]
                if not widths:raise Unsupported('calloc requires one uint32 element-width argument')
                width=1 if 1 in widths else 0
                arguments=['4u' if i==width else allocation_size(a,bytes=False) for i,a in enumerate(args)]
            invocation=callee+'('+', '.join(arguments)+')'
            if callee=='free':builder.lines.append('    '+invocation+';')
            else:values[out]=heap_binding(invocation)
            metrics['calls']+=1
            metrics['allocator_events']=metrics.get('allocator_events',0)+1
        elif calls and code in ('CALL','CALLIND'):
            if code=='CALLIND':
                target=read(inputs[0]) if inputs else None
                if not guarded or not isinstance(target,CodePointer):raise Unsupported('indirect call target is not a public code parameter')
                spec=parameters[target.slot];callee=parameter_name(target.slot)
            else:spec=signatures.get(op.get('callee'));callee=op.get('callee')
            if not spec or len(args)!=len(spec["parameters"]) or not inputs:
                raise Unsupported("unknown or mismatched direct call ABI")
            if (spec["returns"]=="void" and out is not None) or (out is not None and bits!=32):
                raise Unsupported("call return storage disagrees with public ABI")
            arguments=[]
            for value,p in zip(args,spec["parameters"]):
                if p["kind"] in ("uint32","int32"):
                    if not isinstance(value,Value) or value.bits!=32:raise Unsupported("call scalar argument is not uint32")
                    atom=value.atom
                    if call_argument_offset and callee!=name:
                        atom=f"({atom}+{call_argument_offset & 0xffffffff}u)";call_argument_offset=0
                    arguments.append('(int)('+atom+')' if p['kind']=='int32' else atom)
                elif p['kind']=='file-stream':
                    if not isinstance(value,StreamPointer):raise Unsupported('stdio argument is not an opaque stream parameter')
                    arguments.append(parameter_name(value.slot))
                else:
                    if not isinstance(value,Pointer) or parameters[value.slot]["kind"]!=p["kind"] or (parameters[value.slot]["read_only"] and not p["read_only"]):
                        raise Unsupported("call pointer argument type/constness mismatch")
                    arguments.append(address(value,32 if p["kind"]=="uint32-buffer" else 8,argument=True))
            invocation=callee+"("+", ".join(arguments)+")"
            if spec['returns']=='int32':invocation='(unsigned int)('+invocation+')'
            if out is not None:values[out]=builder.emit(32,invocation)
            else:builder.lines.append("    "+invocation+";")
            metrics["calls"]+=1
        elif code in ("LOAD", "STORE"):
            if len(args) != (2 if code == "LOAD" else 3) or constant(args[0]) != space["id"]:
                raise Unsupported("invalid load/store address space or arity")
            if code == "LOAD":
                if bits != 32 and not (extended and bits == 8):
                    raise Unsupported("only exact uint32 loads are supported")
                values[out] = builder.emit(bits, "((unsigned int)(" + address(args[1],bits) + "))" if extended else address(args[1]))
                metrics["loads"] += 1
            else:
                value = args[2]
                if not isinstance(value, Value) or (value.bits != 32 and not (extended and value.bits == 8)):
                    raise Unsupported("only exact uint32 stores are supported")
                expression = value.atom
                # Legacy all-store mutation is retained for historical replay.
                # Mutating only the final store avoids cancellations across
                # earlier stores and guarantees an observable memory change.
                offset = store_offset + (final_store_offset if not heap and not (guarded and graph is not None) and oi == final_store else 0)
                if offset:
                    expression = f"({expression} + {offset & 0xffffffff}u)"
                destination=address(args[1], value.bits, write=True)
                if not (isinstance(args[1],Pointer) and objects[args[1].slot].get('heap_name')):
                    metrics['public_stores']+=1
                    path_public_store=(destination,expression)
                builder.lines.append(f"    {destination} = {expression};")
                metrics["stores"] += 1
        elif code=="CSRD_SELECT":
            if len(args)!=3 or any(not isinstance(a,Value) for a in args) or bits!=args[1].bits:
                raise Unsupported("pointer or malformed scalar merge")
            values[out]=select(*args)
        elif code in ('BOOL_AND','BOOL_OR','BOOL_XOR'):
            # Ghidra's Boolean operations assume canonical one-bit values in
            # byte storage: ghidra.re/ghidra_docs/languages/html/pcodedescription.html
            if bits!=8 or len(args)!=2 or any(not isinstance(a,Value) or a.bits!=8 or bound(a)>1 for a in args):
                raise Unsupported('Boolean operations require proved canonical byte inputs')
            values[out]=operation({'BOOL_AND':'INT_AND','BOOL_OR':'INT_OR','BOOL_XOR':'INT_XOR'}[code],bits,args)
        elif any(isinstance(a,(CodePointer,StreamPointer)) for a in args):
            if code not in ('COPY','CAST') or len(args)!=1 or bits!=pointer_bits:
                raise Unsupported('opaque handles admit only identity copies and contracted calls')
            values[out]=args[0]
        elif any(isinstance(a, Pointer) for a in args):
            metrics["pointer_operations"] += 1
            if heap and code in ('INT_EQUAL','INT_NOTEQUAL') and len(args)==2 and bits==8:
                pointer=next((a for a in args if isinstance(a,Pointer)),None)
                null=next((a for a in args if isinstance(a,Value) and a.bits==pointer_bits and a.known==0),None)
                if pointer is not None and null is not None:
                    values[out]=builder.emit(8,heap_base(pointer)+(' == 0' if code=='INT_EQUAL' else ' != 0'))
                    bounds[values[out]]=1
                    return
            if graph is not None and code in COMPARE and len(args)==2 and all(isinstance(a,Pointer) for a in args):
                if args[0].slot!=args[1].slot:raise Unsupported('pointer comparisons require one shared base')
                offsets=[a.offset if isinstance(a.offset,Value) else literal(pointer_bits,a.offset) for a in args]
                values[out]=operation(code,bits,offsets);return
            if bits != pointer_bits:
                raise Unsupported("pointer width changed or escaped to integer data")
            if code in ("COPY", "CAST") and len(args) == 1:
                values[out] = args[0]
                return
            if code == "INT_ADD" and len(args) == 2 and isinstance(args[1], Pointer):
                args = [args[1], args[0]]
            if not isinstance(args[0], Pointer):
                raise Unsupported("unsupported pointer operation")
            base = args[0]
            if (records and code=="PTRSUB" and len(args)==2 and isinstance(args[1],Value) and
                args[1].known==0 and args[1].bits<=pointer_bits):
                # Union member selection uses a zero-byte offset that Ghidra
                # may spell as uint32 even when pointers are uint64.
                args[1]=literal(pointer_bits,0)
            if extended and ((isinstance(base.offset,Value)) or any(a.known is None for a in args[1:])):
                if code == "PTRADD" and len(args)==3:
                    delta=operation("INT_MULT",pointer_bits,args[1:])
                elif code in ("PTRSUB","INT_ADD") and len(args)==2: delta=args[1]
                else: raise Unsupported("unsupported dynamic pointer operation")
                if any(a.bits!=pointer_bits for a in args): raise Unsupported("pointer arithmetic width mismatch")
                initial=base.offset if isinstance(base.offset,Value) else literal(pointer_bits,base.offset)
                values[out]=Pointer(pointer_bits,base.slot,operation("INT_ADD",pointer_bits,[initial,delta]))
                return
            if code == "PTRADD" and len(args) == 3:
                delta = constant(args[1]) * constant(args[2])
            elif code in ("PTRSUB", "INT_ADD", "INT_SUB") and len(args) == 2:
                delta = constant(args[1]) * (-1 if code == "INT_SUB" else 1)
                # PTRSUB denotes struct-field offset addition, not subtraction.
            else:
                raise Unsupported("unsupported pointer operation or arity")
            if any(a.bits != pointer_bits for a in args):
                raise Unsupported("pointer arithmetic width mismatch")
            values[out] = Pointer(pointer_bits, base.slot, (base.offset + delta) % (1 << pointer_bits))
        else:
            # Keep reconstructed C inside the buffer source verifier's arithmetic
            # contract. Shift-by-constant is exact uint32 scaling, including zero
            # for counts >=32 under P-code's total shift semantics.
            if extended and code in SCALAR:
                values[out]=operation(code,bits,args)
            elif code == "INT_LEFT" and len(args) == 2 and bits == args[0].bits == 32:
                count = constant(args[1])
                values[out] = builder.operation("INT_MULT", 32, [args[0], literal(32, (1 << count) if count < 32 else 0)])
            elif code == "INT_NEGATE" and len(args) == 1 and bits == args[0].bits == 32:
                values[out] = builder.operation("INT_SUB", 32, [literal(32, 0xffffffff), args[0]])
            elif code in ("COPY", "CAST", "INT_ADD", "INT_SUB", "INT_MULT", "INT_2COMP") and bits == 32:
                values[out] = builder.operation(code, bits, args)
            elif all(a.known is not None for a in args) and code in ("COPY", "CAST", "INT_ADD", "INT_SUB", "INT_MULT"):
                values[out] = builder.operation(code, bits, args)
            else:
                raise Unsupported(f"scalar operation outside buffer observer contract: {code}")
        if len(builder.lines) > LIMITS["emitted_statements"]:
            raise Unsupported("emitted statement budget exceeded")

    def refine(condition,truth):
        if condition not in predicates:return True
        code,a,b,negated=predicates[condition];truth=truth!=negated
        if a.known is not None and b.known is None:
            if code in ('INT_EQUAL','INT_NOTEQUAL'):a,b=b,a
            elif code in ('INT_LESS','INT_LESSEQUAL'):
                a,b=b,a;code='INT_LESSEQUAL' if code=='INT_LESS' else 'INT_LESS';truth=not truth
            else:return True
        if b.known is None:return True
        n=b.known;lo,hi=minimum(a),bound(a)
        if code=='INT_LESS':
            if truth:hi=min(hi,n-1)
            else:lo=max(lo,n)
        elif code=='INT_LESSEQUAL':
            if truth:hi=min(hi,n)
            else:lo=max(lo,n+1)
        elif code in ('INT_EQUAL','INT_NOTEQUAL'):
            if truth==(code=='INT_EQUAL'):lo,hi=max(lo,n),min(hi,n)
            else:excluded.setdefault(a,set()).add(n)
        else:return True
        step=multiple(a)
        lo=((lo+step-1)//step)*step;hi=(hi//step)*step
        while lo<=hi and lo in excluded.get(a,()):lo+=step
        while lo<=hi and hi in excluded.get(a,()):hi-=step
        if lo>hi:return False
        # Independent SSA temporaries can compute exactly the same total scalar
        # expression. Share facts, never C variable names or speculative loads.
        for peer in identical_scalars.get(origins.get(a),{a}):
            lower[peer]=max(lower.get(peer,0),lo);bounds[peer]=min(bound(peer),hi)
            excluded.setdefault(peer,set()).update(excluded.get(a,()))
        return True

    if graph is None:
        for oi,op in enumerate(ops):process(oi,op)
    else:
        metrics.update(observer='bounded-owned-heap-v1' if heap else 'ordered-stdio-buffers-v1' if stdio else 'guarded-calls-buffers-v2' if guarded else 'bounded-guarded-memory-v1',block_expansions=0,terminal_paths=0,constant_branches=0,symbolic_branches=0,max_path_block_entries=0)
        def walk(bid,incoming,environment,limits,depth,last_store=None):
            nonlocal values,bounds,lower,excluded,path_public_store
            metrics['block_expansions']+=1;metrics['max_path_block_entries']=max(metrics['max_path_block_entries'],depth)
            if depth>LIMITS['path_block_entries'] or metrics['block_expansions']>LIMITS['block_expansions']:
                raise Unsupported('complete memory CFG expansion exceeds block budget')
            values=environment.copy();bounds,lower,excluded=limits[0].copy(),limits[1].copy(),{v:set(s) for v,s in limits[2].items()}
            path_public_store=last_store
            body=graph.blocks[bid]
            phis=[ops[i] for i in body['operations'] if ops[i]['opcode']=='MULTIEQUAL']
            merged={op['output']:values[op['inputs'][incoming]] for op in phis}
            for oi in body['operations']:
                if 'output' in ops[oi]:values.pop(ops[oi]['output'],None)
            values.update(merged)
            for oi in body['operations']:
                op=ops[oi];code=op['opcode']
                if code in ('MULTIEQUAL','BRANCH','CBRANCH'):continue
                process(oi,op)
                if code=='RETURN':
                    metrics['terminal_paths']+=1
                    if metrics['terminal_paths']>LIMITS['terminal_paths']:raise Unsupported('complete memory CFG expansion exceeds path budget')
                    return
            env=values.copy();snapshot=(bounds.copy(),lower.copy(),{v:set(s) for v,s in excluded.items()});last_store=path_public_store
            def successor(slot,condition=None):
                nonlocal bounds,lower,excluded
                bounds,lower,excluded=snapshot[0].copy(),snapshot[1].copy(),{v:set(s) for v,s in snapshot[2].items()}
                if condition is not None and not refine(condition,bool(slot)):
                    # Exact interval contradiction, never a heuristic path cut.
                    builder.lines.append('    return 0u;');return
                edge=body['outgoing'][slot]
                walk(edge['block'],edge['reverse_index'],env,(bounds,lower,excluded),depth+1,last_store)
            last=ops[body['operations'][-1]] if body['operations'] else None
            if last and last['opcode']=='CBRANCH':
                condition=read(last['inputs'][1])
                if not isinstance(condition,Value) or condition.bits!=8:raise Unsupported('nonboolean memory branch')
                if condition.known is not None:
                    metrics['constant_branches']+=1;successor(int(condition.known!=0));return
                metrics['symbolic_branches']+=1
                builder.lines.append('    if ('+condition.atom+' != 0u) {');successor(1,condition)
                builder.lines.append('    } else {');successor(0,condition);builder.lines.append('    }')
            else:successor(0)
        walk(graph.entry,None,values,(bounds,lower,excluded),1)
    if (heap or guarded) and final_store_offset:
        if not metrics['public_stores']:raise Unsupported('no public store for the observable-memory corruption control')
    expression = result.atom if graph is None else '0u'
    if result_offset:
        expression = f"({expression} + {result_offset & 0xffffffff}u)"
    signature = ", ".join((("void" if p['returns']=='void' else 'unsigned int')+' (*'+parameter_name(i)+')('+call_types(p)+')') if p['kind']=='function-pointer' else ("const " if p["read_only"] else "") + ctype(p) +
                          (" *" if p["kind"] != "uint32" else " ") + f"p{i}"
                          for i, p in enumerate(parameters))
    lines = builder.lines + ([] if graph is not None else [f"    (void)v{i};" for i in range(builder.serial)]) + [f"    (void){parameter_name(i)};" for i in range(arity)] + [f"    return {expression};"]
    source = ("\n".join(declarations)+"\n" if declarations else "")+f"unsigned int {name}({signature}) {{\n" + "\n".join(lines) + "\n}\n"
    if len(source.encode()) > LIMITS["generated_bytes"]:
        raise Unsupported("generated source budget exceeded")
    metrics.update(generated_bytes=len(source.encode()), emitted_statements=len(builder.lines))
    return source


def main():
    """One binary-only adapter attempt; grading runs in a separate process."""
    import argparse
    import json
    from pathlib import Path
    import resource
    import sys
    import time
    from audit_protection import file_hash, write_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "export_sha256": file_hash(args.export), "metrics": {}}
    try:
        data = json.loads(Path(args.export).read_text())
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            source = reconstruct(data, metrics=report["metrics"])
        finally:
            report["reconstruction_wall_seconds"] = time.perf_counter() - wall
            report["reconstruction_cpu_seconds"] = time.process_time() - cpu
        (root / "recovered.c").write_text(source)
        report.update(status="candidate", recovered_sha256=file_hash(root / "recovered.c"))
    except Unsupported as error:
        report.update(status="unsupported", reason=str(error))
    except Exception as error:
        report.update(status="error", reason=str(error))
    report["peak_process_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    report["rss_scope"] = "whole adapter process high-water mark, including Python/imports; not per-reconstruction allocation"
    if file_hash(args.export) != report["export_sha256"]:
        report.update(status="error", reason="export changed during reconstruction")
    write_json(root / "adapter.json", report)
    return {"candidate": 0, "unsupported": 2, "error": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
