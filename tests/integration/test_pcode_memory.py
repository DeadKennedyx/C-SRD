"""Memory-observer semantics, alias-sensitive controls and fail-closed exports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from pcode_memory import reconstruct, Unsupported

TOOL = str(Path(sys.argv.pop(1)).resolve())


class Export:
    def __init__(self, readonly=False):
        self.data = {"schema_version": 4, "memory_model": "ordered-u32-buffers-v1", "function": "f",
                     "arity": 3, "parameters": [{"kind": "uint32-buffer", "read_only": readonly},
                                                {"kind": "uint32-buffer", "read_only": False},
                                                {"kind": "uint32", "read_only": False}],
                     "address_space": {"id": 433, "pointer_bytes": 8, "addressable_unit_bytes": 1},
                     "entry_block": 0, "operation_order": "basic-block-live-order",
                     "nodes": [], "operations": [],
                     "blocks": [{"id": 0, "incoming": [], "outgoing": [], "operations": []}]}
        self.p = self.node(8, input=True, parameter=0)
        self.q = self.node(8, input=True, parameter=1)
        self.x = self.node(4, input=True, parameter=2)
        self.space = self.constant(433, 4)
        self.destination = self.constant(0, 8)

    def node(self, size, **fields):
        result = len(self.data["nodes"])
        self.data["nodes"].append({"size": size, **fields})
        return result

    def constant(self, value, size=4):
        return self.node(size, constant=str(value))

    def op(self, code, inputs, size=4):
        output = self.node(size) if size else None
        item = {"opcode": code, "inputs": inputs, "block": 0}
        if output is not None:
            item["output"] = output
        self.data["blocks"][0]["operations"].append(len(self.data["operations"]))
        self.data["operations"].append(item)
        return output

    def load(self, pointer):
        return self.op("LOAD", [self.space, pointer])

    def store(self, pointer, value):
        self.op("STORE", [self.space, pointer, value], size=None)

    def finish(self, value):
        self.op("RETURN", [self.destination, value], size=None)
        return self.data


def snapshot():
    e = Export()
    before = e.load(e.p)
    e.store(e.q, e.x)
    after = e.load(e.p)
    result = e.op("INT_ADD", [before, after])
    return e.finish(result)


def byte_diamond():
    e=Export()
    e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
    e.data["parameters"][0].update(kind="unsigned-char-buffer",element_signed=False)
    masked=e.op("INT_AND",[e.x,e.constant(7)])
    cap=e.constant(3)
    condition=e.op("INT_LESS",[cap,masked],size=1)
    e.op("CBRANCH",[e.destination,condition],size=None)
    first=len(e.data["operations"])
    no=e.op("COPY",[masked]);e.op("BRANCH",[e.destination],size=None)
    second=len(e.data["operations"])
    yes=e.op("COPY",[cap]);e.op("BRANCH",[e.destination],size=None)
    join=len(e.data["operations"])
    merged=e.op("MULTIEQUAL",[no,yes])
    wide=e.op("INT_ZEXT",[merged],size=8)
    pointer=e.op("PTRADD",[e.p,wide,e.constant(1,8)],size=8)
    value=e.op("LOAD",[e.space,pointer],size=1)
    data=e.finish(e.op("INT_ZEXT",[value]))
    def edge(block,reverse):return {"block":block,"reverse_index":reverse}
    ranges=[(0,first),(first,second),(second,join),(join,len(data["operations"]))]
    incoming=[[],[edge(0,0)],[edge(0,1)],[edge(1,0),edge(2,0)]]
    outgoing=[[edge(1,0),edge(2,0)],[edge(3,0)],[edge(3,1)],[]]
    data["blocks"]=[]
    for i,(begin,end) in enumerate(ranges):
        for op in data["operations"][begin:end]:op["block"]=i
        data["blocks"].append({"id":i,"operations":list(range(begin,end)),"incoming":incoming[i],"outgoing":outgoing[i]})
    return data


def guarded_graph(loop=False, comparison='INT_LESS'):
    e=Export();e.data.update(schema_version=8,memory_model='records-state-buffers-v1',persistent_objects=[],call_signatures={})
    if loop:
        limit=e.op('INT_AND',[e.x,e.constant(3)])
        e.op('BRANCH',[e.destination],size=None);header=len(e.data['operations'])
        phi=e.op('MULTIEQUAL',[e.constant(0),e.constant(0)])
        phi_op=e.data['operations'][-1]
        condition=e.op(comparison,[phi,limit],size=1)
        e.op('CBRANCH',[e.destination,condition],size=None);body=len(e.data['operations'])
        offset=e.op('INT_ZEXT',[phi],size=8)
        pointer=e.op('PTRADD',[e.p,offset,e.constant(4,8)],size=8)
        e.store(pointer,e.op('INT_ADD',[e.x,phi]))
        increment=e.op('INT_ADD',[phi,e.constant(1)]);phi_op['inputs'][1]=increment
        e.op('BRANCH',[e.destination],size=None);end=len(e.data['operations'])
        data=e.finish(e.load(e.q));ranges=[(0,header),(header,body),(body,end),(end,len(data['operations']))]
        incoming=[[],[0,2],[1],[1]];outgoing=[[1],[3,2],[1],[]]
    else:
        condition=e.op('INT_NOTEQUAL',[e.x,e.constant(0)],size=1)
        e.op('CBRANCH',[e.destination,condition],size=None);no=len(e.data['operations'])
        e.store(e.q,e.op('INT_MULT',[e.x,e.constant(3)]));e.finish(e.load(e.p));yes=len(e.data['operations'])
        e.store(e.p,e.op('INT_ADD',[e.x,e.constant(1)]));data=e.finish(e.load(e.q))
        ranges=[(0,no),(no,yes),(yes,len(data['operations']))];incoming=[[],[0],[0]];outgoing=[[1,2],[],[]]
    data['blocks']=[]
    for i,(begin,end) in enumerate(ranges):
        for op in data['operations'][begin:end]:op['block']=i
        data['blocks'].append({'id':i,'operations':list(range(begin,end)),'incoming':incoming[i],'outgoing':outgoing[i]})
    return data


def duplicate_bound_graph():
    e=Export();e.data.update(schema_version=8,memory_model='records-state-buffers-v1',persistent_objects=[],call_signatures={})
    checked=e.op('INT_AND',[e.x,e.constant(3)])
    used=e.op('INT_AND',[e.x,e.constant(3)])
    zero=e.op('INT_EQUAL',[checked,e.constant(0)],size=1)
    e.op('CBRANCH',[e.destination,zero],size=None);setup=len(e.data['operations'])
    last=e.op('INT_SUB',[used,e.constant(1)])
    wide=e.op('INT_ZEXT',[last],size=8)
    end=e.op('PTRADD',[e.p,wide,e.constant(4,8)],size=8)
    e.op('BRANCH',[e.destination],size=None);header=len(e.data['operations'])
    pointer=e.op('MULTIEQUAL',[e.p,e.p],size=8);phi=e.data['operations'][-1]
    e.store(pointer,e.x)
    done=e.op('INT_EQUAL',[pointer,end],size=1)
    e.op('CBRANCH',[e.destination,done],size=None);increment=len(e.data['operations'])
    advanced=e.op('PTRADD',[pointer,e.constant(1,8),e.constant(4,8)],size=8);phi['inputs'][1]=advanced
    e.op('BRANCH',[e.destination],size=None);exit_=len(e.data['operations'])
    data=e.finish(e.load(e.q));ranges=[(0,setup),(setup,header),(header,increment),(increment,exit_),(exit_,len(data['operations']))]
    incoming=[[],[0],[1,3],[2],[0,2]];outgoing=[[1,4],[2],[3,4],[2],[]]
    data['blocks']=[]
    for i,(begin,end_) in enumerate(ranges):
        for op in data['operations'][begin:end_]:op['block']=i
        data['blocks'].append({'id':i,'operations':list(range(begin,end_)),'incoming':incoming[i],'outgoing':outgoing[i]})
    return data


def heap_graph(callee='malloc',dynamic=False,private_tail=False):
    e=Export();e.data.update(schema_version=5,memory_model='ordered-byte-buffers-v2')
    args=[e.constant(4,8)]
    if callee=='calloc':
        count=e.constant(1,8)
        if dynamic:
            masked=e.op('INT_AND',[e.x,e.constant(3)])
            ordinary=e.op('INT_ADD',[masked,e.constant(1)])
            scaled=e.op('INT_MULT',[ordinary,e.constant(3)])
            encoded=e.op('INT_ADD',[scaled,e.constant(4294967294)])
            removed=e.op('INT_SUB',[encoded,e.constant(4294967294)])
            decoded=e.op('INT_MULT',[removed,e.constant(2863311531)])
            count=e.op('INT_ZEXT',[decoded],size=8)
        args=[count,e.constant(4,8)]
    if callee=='realloc':args=[e.constant(0,8),e.constant(4,8)]
    pointer=e.op('CALL',[e.destination,*args],size=8);e.data['operations'][-1]['callee']=callee
    condition=e.op('INT_EQUAL',[pointer,e.constant(0,8)],size=1)
    e.op('CBRANCH',[e.destination,condition],size=None);yes=len(e.data['operations'])
    value=e.op('INT_ADD',[e.x,e.constant(3)]);e.store(pointer,value)
    after=e.load(pointer);e.store(e.p,after)
    if private_tail:e.store(pointer,e.constant(99))
    e.op('CALL',[e.destination,pointer],size=None);e.data['operations'][-1]['callee']='free'
    e.finish(after);no=len(e.data['operations'])
    data=e.finish(e.op('INT_ADD',[e.x,e.constant(1)]))
    ranges=[(0,yes),(yes,no),(no,len(data['operations']))]
    incoming=[[],[0],[0]];outgoing=[[1,2],[],[]];data['blocks']=[]
    for i,(begin,end) in enumerate(ranges):
        for op in data['operations'][begin:end]:op['block']=i
        data['blocks'].append({'id':i,'operations':list(range(begin,end)),'incoming':incoming[i],'outgoing':outgoing[i]})
    return data


class MemoryReconstruction(unittest.TestCase):
    def test_heap_calls_null_branches_and_public_effects(self):
        for callee,arguments in [('malloc','4u'),('calloc','1u,4u'),('realloc','0,4u')]:
            data=heap_graph(callee);metrics={}
            reference='#include <stdlib.h>\nunsigned f(unsigned*p,unsigned*q,unsigned x){(void)q;'
            reference+=f'unsigned*h={callee}({arguments});if(!h)return x+1u;*h=x+3u;'
            reference+='unsigned r=*h;*p=r;free(h);return r;}'
            with self.subTest(callee=callee):
                self.grade(reference,reconstruct(data,metrics=metrics))
                self.assertEqual(metrics['allocator_events'],2)
                self.grade(reference,reconstruct(data,result_offset=1),'counterexample')
                self.grade(reference,reconstruct(data,final_store_offset=1),'counterexample')

    def test_heap_observer_rejects_unknown_calls_and_invalid_abi(self):
        for fault in ('extent','alignment','size_width','result_width','free_public','opaque','indirect','escaped'):
            bad=heap_graph();ops=bad['operations'];nodes=bad['nodes'];allocate=ops[0]
            release=next(o for o in ops if o.get('callee')=='free')
            if fault=='extent':nodes[allocate['inputs'][1]]['constant']='132'
            elif fault=='alignment':nodes[allocate['inputs'][1]]['constant']='5'
            elif fault=='size_width':nodes[allocate['inputs'][1]]['size']=4
            elif fault=='result_width':nodes[allocate['output']]['size']=4
            elif fault=='free_public':release['inputs'][1]=0
            elif fault=='opaque':release['callee']='unknown_effect'
            elif fault=='indirect':release['opcode']='CALLIND'
            else:
                store=next(o for o in ops if o['opcode']=='STORE');store['inputs'][2]=allocate['output']
            with self.subTest(fault=fault),self.assertRaises(Unsupported):reconstruct(bad)

    def test_allocator_extent_uses_exact_modular_range_normalization(self):
        data=heap_graph('calloc',dynamic=True)
        reference='#include <stdlib.h>\nunsigned f(unsigned*p,unsigned*q,unsigned x){(void)q;'
        reference+='unsigned*h=calloc((x&3u)+1u,4u);if(!h)return x+1u;*h=x+3u;'
        reference+='unsigned r=*h;*p=r;free(h);return r;}'
        self.grade(reference,reconstruct(data))
        bad=copy.deepcopy(data)
        inverse=next(n for n in bad['nodes'] if n.get('constant')=='2863311531')
        inverse['constant']='2863311533'
        self.grade(reference,reconstruct(bad),'counterexample')
        inverse['constant']='2863311534'
        with self.assertRaisesRegex(Unsupported,'extent'):reconstruct(bad)

    def test_heap_corruption_control_changes_public_memory(self):
        data=heap_graph(private_tail=True);metrics={}
        candidate=reconstruct(data,metrics=metrics)
        self.assertEqual(metrics['stores'],3)
        self.assertEqual(metrics['public_stores'],1)
        self.grade(candidate,reconstruct(data,final_store_offset=1),'counterexample')

    def test_duplicate_scalar_bound_controls_pointer_loop(self):
        data=duplicate_bound_graph();metrics={}
        source='unsigned f(unsigned*p,unsigned*q,unsigned x){unsigned n=x&3u;for(unsigned i=0u;i<n;++i){p[i]=x;}return *q;}'
        self.grade(source,reconstruct(data,metrics=metrics))
        self.assertLess(metrics['block_expansions'],30)
        self.grade(source,reconstruct(data,final_store_offset=1),'counterexample')
        bad=copy.deepcopy(data)
        bad['nodes'][bad['operations'][1]['inputs'][1]]['constant']='6'
        with self.assertRaises(Unsupported):reconstruct(bad)

    def test_lossless_high_pcode_width_normalization(self):
        # Ghidra can retain wider inputs while narrowing a masked boolean
        # temporary. Only range-preserving repairs are eligible for grading.
        e=Export();e.data.update(schema_version=8,memory_model='records-state-buffers-v1',persistent_objects=[],call_signatures={})
        masked=e.op('INT_AND',[e.load(e.p),e.constant(1)],size=1)
        condition=e.op('INT_EQUAL',[masked,e.constant(0)],size=1)
        result=e.op('INT_ZEXT',[condition]);e.store(e.q,result);data=e.finish(result)
        metrics={};candidate=reconstruct(data,metrics=metrics)
        self.grade('unsigned f(unsigned*p,unsigned*q,unsigned x){(void)x;unsigned r=(*p&1u)==0u;*q=r;return r;}',candidate)
        self.assertEqual(metrics['lossless_width_normalizations'],2)
        self.grade(candidate,reconstruct(data,final_store_offset=1),'counterexample')
        for fault in ('lost_bits','nonconstant_comparand','nonfitting_constant','legacy_schema'):
            bad=copy.deepcopy(data)
            if fault=='lost_bits':bad['nodes'][bad['operations'][1]['inputs'][1]]['constant']='256'
            elif fault=='nonconstant_comparand':bad['operations'][2]['inputs'][1]=e.x
            elif fault=='nonfitting_constant':bad['nodes'][bad['operations'][2]['inputs'][1]]['constant']='256'
            else:bad.update(schema_version=4,memory_model='ordered-u32-buffers-v1')
            with self.subTest(fault=fault),self.assertRaises(Unsupported):reconstruct(bad)

    def test_selected_large_scales_and_small_bounded_multiplication(self):
        data=byte_diamond();data.update(schema_version=8,memory_model='records-state-buffers-v1',persistent_objects=[],call_signatures={})
        data['parameters'][0]={'kind':'uint32-buffer','read_only':False}
        # Independent CFG with either large constant feeding one machine multiply.
        ph=next(o for o in data['operations'] if o['opcode']=='MULTIEQUAL')
        for node,value in zip(ph['inputs'],(1073741823,2147483647)):
            definition=next(o for o in data['operations'] if o.get('output')==node)
            constant=len(data['nodes']);data['nodes'].append({'size':4,'constant':str(value),'input':False})
            definition['inputs']=[constant]
        join=data['blocks'][-1];phi_index=join['operations'][0]
        data['operations']=data['operations'][:phi_index+1]
        product=len(data['nodes']);data['nodes'].append({'size':4,'input':False})
        data['operations'].append({'opcode':'INT_MULT','inputs':[2,ph['output']],'output':product,'block':join['id']})
        data['operations'].append({'opcode':'STORE','inputs':[3,0,product],'block':join['id']})
        data['operations'].append({'opcode':'RETURN','inputs':[4,product],'block':join['id']})
        join['operations']=list(range(phi_index,len(data['operations'])))
        source='unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){(void)q;unsigned int v=(x&7u)>3u ? 2147483647u*x : 1073741823u*x;*p=v;return v;}'
        self.grade(source,reconstruct(data))
        e=Export();e.data.update(schema_version=8,memory_model='records-state-buffers-v1',persistent_objects=[],call_signatures={})
        k=e.op('INT_AND',[e.x,e.constant(3)]);v=e.op('INT_MULT',[k,e.load(e.p)]);e.store(e.q,v)
        source='unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){unsigned int v=0u;if(x&1u)v=*p;if(x&2u)v=v+2u*(*p);*q=v;return v;}'
        self.grade(source,reconstruct(e.finish(v)))

    def test_conditional_effects_early_returns_and_bounded_loops(self):
        source='unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){if(x){*p=x+1u;return *q;}*q=3u*x;return *p;}'
        metrics={};data=guarded_graph()
        self.grade(source,reconstruct(data,metrics=metrics))
        self.assertEqual(metrics['observer'],'bounded-guarded-memory-v1')
        self.grade(source,reconstruct(data,result_offset=1),'counterexample')
        for comparison in ('INT_LESS','INT_NOTEQUAL'):
            data=guarded_graph(True,comparison);metrics={}
            source='unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){unsigned int n=x&3u;for(unsigned int i=0u;i<n;++i){p[i]=x+i;}return *q;}'
            self.grade(source,reconstruct(data,metrics=metrics))
            self.assertGreater(metrics['block_expansions'],4)
            self.grade(source,reconstruct(data,final_store_offset=1),'counterexample')

    def test_unbounded_or_nonterminating_memory_cfg_fails_closed(self):
        data=guarded_graph(True)
        data['operations'][0].update(opcode='COPY',inputs=[2])
        with self.assertRaises(Unsupported):reconstruct(data)
        data=guarded_graph(True)
        increment=next(o for o in reversed(data['operations']) if o['opcode']=='INT_ADD')
        data['nodes'][increment['inputs'][1]]['constant']='0'
        with self.assertRaises(Unsupported):reconstruct(data)

    def test_record_dynamic_fields_and_global_linkage(self):
        layout={"tag":"pair","union":False,"bytes":8,"alignment":4,"fields":[
            {"name":"a","kind":"uint32","byte_offset":0},{"name":"b","kind":"uint32","byte_offset":4}]}
        e=Export();e.data.update(schema_version=8,memory_model="records-state-buffers-v1",persistent_objects=[],call_signatures={})
        e.data["parameters"][0].update(kind="record-buffer",record=layout)
        mask=e.op("INT_AND",[e.x,e.constant(1)])
        wide=e.op("INT_ZEXT",[mask],size=8)
        pointer=e.op("PTRADD",[e.p,wide,e.constant(8,8)],size=8)
        pointer=e.op("PTRSUB",[pointer,e.constant(4,8)],size=8)
        e.store(pointer,e.x);data=e.finish(e.load(e.q))
        self.grade("struct pair{unsigned a;unsigned b;};unsigned f(struct pair*p,unsigned*q,unsigned x){p[x&1u].b=x;return *q;}",reconstruct(data))
        self.grade(reconstruct(data),reconstruct(data,final_store_offset=1),"counterexample")
        e=Export();e.data.update(schema_version=8,memory_model="records-state-buffers-v1",call_signatures={},
                                persistent_objects=[{"name":"g","kind":"uint32-buffer","address":"4096"}])
        pointer=e.node(8,input=True,linkage_pointer="g",storage="GOT-slot")
        after=e.op("INDIRECT",[pointer,e.constant(9)],size=8)
        e.data["nodes"][after].update(linkage_pointer="g",storage="GOT-slot")
        e.store(pointer,e.x);result=e.load(after);data=e.finish(result)
        self.grade("unsigned g;unsigned f(unsigned*p,unsigned*q,unsigned x){(void)p;(void)q;g=x;return g;}",reconstruct(data))
        bad=copy.deepcopy(data);del bad["nodes"][after]["linkage_pointer"]
        with self.assertRaisesRegex(Unsupported,"INDIRECT"):reconstruct(bad)

    def test_union_narrow_zero_offset(self):
        e=Export();e.data.update(schema_version=8,memory_model="records-state-buffers-v1",persistent_objects=[],call_signatures={})
        e.data["parameters"][0].update(kind="record-buffer",record={"tag":"word","union":True,"bytes":4,"alignment":4,
            "fields":[{"name":"a","kind":"uint32","byte_offset":0},{"name":"b","kind":"uint32","byte_offset":0}]})
        at=e.op("PTRSUB",[e.p,e.constant(0)],size=8)
        e.store(at,e.x);data=e.finish(e.load(at))
        self.grade("union word{unsigned a;unsigned b;};unsigned f(union word*p,unsigned*q,unsigned x){(void)q;p->b=x;return p->a;}",reconstruct(data))

    def grade(self, reference, candidate, expected="proved-under-model", calls=False):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.c").write_text(reference + "\n")
            (p / "b.c").write_text(candidate)
            process = subprocess.run([TOOL, "verify", p / "a.c", p / "b.c", "--report", p / "report.json",
                                      *(["--call-contracts",ROOT/"tests/fixtures/calls.json"] if calls else [])],
                                     capture_output=True, text=True)
            report = json.loads((p / "report.json").read_text())
            f, = report["functions"]
            self.assertEqual(f["verification"], expected, process.stderr + str(f))
            self.assertEqual(process.returncode, 0 if expected == "proved-under-model" else 3)
            return f

    def test_ordered_call_dynamic_word_pointer_and_effect_control(self):
        e=Export()
        e.data.update(schema_version=7,memory_model="ordered-calls-buffers-v1",call_signatures={
            "effect_mix":{"returns":"uint32","parameters":[{"kind":k,"read_only":False} for k in ("uint32-buffer","uint32-buffer","uint32")]}})
        before=e.load(e.p)
        mask=e.op("INT_AND",[e.x,e.constant(3)])
        wide=e.op("INT_ZEXT",[mask],size=8)
        pointer=e.op("PTRADD",[e.p,wide,e.constant(4,8)],size=8)
        e.op("CALL",[e.destination,pointer,e.q,e.x],size=None)
        e.data["operations"][-1]["callee"]="effect_mix"
        after=e.load(e.p);data=e.finish(e.op("INT_ADD",[before,after]));metrics={}
        source=reconstruct(data,metrics=metrics)
        reference="unsigned int effect_mix(unsigned int*,unsigned int*,unsigned int);\nunsigned int f(unsigned int*p,unsigned int*q,unsigned int x){unsigned int b=p[0];effect_mix(p+(x&3u),q,x);return b+p[0];}"
        self.grade(reference,source,calls=True)
        self.assertEqual(metrics["calls"],1)
        self.grade(source,reconstruct(data,call_argument_offset=1),"counterexample",calls=True)
        for mutation in ("unknown_symbol","wrong_return","wrong_kind"):
            wrong=copy.deepcopy(data)
            if mutation=="unknown_symbol":wrong["operations"][4]["callee"]="unknown"
            elif mutation=="wrong_return":wrong["call_signatures"]["effect_mix"]["returns"]="float"
            else:wrong["call_signatures"]["effect_mix"]["parameters"][0]["kind"]="unsigned-char-buffer"
            with self.assertRaises(Unsupported):reconstruct(wrong)

    def test_call_pointer_bound_propagates_through_a_scaled_branch(self):
        e=Export()
        e.data.update(schema_version=7,memory_model="ordered-calls-buffers-v1",call_signatures={
            "effect_mix":{"returns":"uint32","parameters":[{"kind":k,"read_only":False} for k in ("uint32-buffer","uint32-buffer","uint32")]}})
        condition=e.op("INT_LESS",[e.x,e.constant(4)],size=1)
        e.op("CBRANCH",[e.destination,condition],size=None)
        first=len(e.data["operations"])
        no=e.op("COPY",[e.constant(12,8)],size=8);e.op("BRANCH",[e.destination],size=None)
        second=len(e.data["operations"])
        wide=e.op("INT_ZEXT",[e.x],size=8)
        yes=e.op("INT_LEFT",[wide,e.constant(2,8)],size=8);e.op("BRANCH",[e.destination],size=None)
        join=len(e.data["operations"])
        merged=e.op("MULTIEQUAL",[no,yes],size=8)
        pointer=e.op("INT_ADD",[e.p,merged],size=8)
        result=e.op("CALL",[e.destination,pointer,e.q,e.x]);e.data["operations"][-1]["callee"]="effect_mix"
        data=e.finish(result)
        edge=lambda block,reverse:{"block":block,"reverse_index":reverse}
        ranges=[(0,first),(first,second),(second,join),(join,len(data["operations"]))]
        incoming=[[],[edge(0,0)],[edge(0,1)],[edge(1,0),edge(2,0)]]
        outgoing=[[edge(1,0),edge(2,0)],[edge(3,0)],[edge(3,1)],[]]
        data["blocks"]=[]
        for i,(begin,end) in enumerate(ranges):
            for op in data["operations"][begin:end]:op["block"]=i
            data["blocks"].append({"id":i,"operations":list(range(begin,end)),"incoming":incoming[i],"outgoing":outgoing[i]})
        reference="unsigned int effect_mix(unsigned int*,unsigned int*,unsigned int);\nunsigned int f(unsigned int*p,unsigned int*q,unsigned int x){return effect_mix(p+(x<=3u?x:3u),q,x);}"
        self.grade(reference,reconstruct(data),calls=True)

    def test_aliasing_load_snapshots_preserved(self):
        reference = "unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){unsigned int v=p[0];q[0]=x;return v+p[0];}"
        data, metrics = snapshot(), {}
        self.grade(reference, reconstruct(data, metrics=metrics))
        self.assertEqual((metrics["loads"], metrics["stores"]), (2, 1))
        self.assertEqual(metrics["footprint_elements"], {"0": 1, "1": 1})
        self.grade(reference, reconstruct(data, result_offset=1), "counterexample")
        # Move the store after the second load. Valid SSA, wrong with aliases.
        data["operations"][1], data["operations"][2] = data["operations"][2], data["operations"][1]
        self.grade(reference, reconstruct(data), "counterexample")

    def test_byte_dynamic_offset_and_word_alias(self):
        e=Export()
        e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
        e.data["parameters"][0].update(kind="unsigned-char-buffer",element_signed=False)
        idx=e.op("INT_AND",[e.x,e.constant(7)])
        wide=e.op("INT_ZEXT",[idx],size=8)
        pointer=e.op("PTRADD",[e.p,wide,e.constant(1,8)],size=8)
        before=e.load(e.q)
        low=e.op("SUBPIECE",[e.x,e.constant(0)],size=1)
        e.store(pointer,low)
        after=e.load(e.q)
        data=e.finish(e.op("INT_ADD",[before,after]))
        metrics={}
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){unsigned int b=q[0];p[x&7u]=x;return b+q[0];}",reconstruct(data,metrics=metrics))
        self.assertEqual(metrics["footprint_elements"],{"0":8,"1":1})
        self.grade(reconstruct(data),reconstruct(data,final_store_offset=1),"counterexample")
        # An unbounded offset must not acquire a false range just from clamping.
        data["operations"][0]["inputs"][1]=e.constant(0xffffffff)
        with self.assertRaises(Unsupported): reconstruct(data)

    def test_signed_byte_load_is_raw_before_sign_extension(self):
        e=Export()
        e.data.update(schema_version=5,memory_model="ordered-byte-buffers-v2")
        e.data["parameters"][0].update(kind="signed-char-buffer",element_signed=True)
        raw=e.op("LOAD",[e.space,e.p],size=1)
        value=e.op("INT_SEXT",[raw])
        data=e.finish(value)
        self.grade("unsigned int f(signed char*p,unsigned int*q,unsigned int x){(void)q;(void)x;return (unsigned int)p[0];}",reconstruct(data))

    def test_scalar_diamond_preserves_clamped_index(self):
        data=byte_diamond();metrics={}
        source=reconstruct(data,metrics=metrics)
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){(void)q;unsigned int i=x&7u;return p[i<=3u?i:3u];}",source)
        self.assertEqual(metrics["scalar_diamonds"],1)
        self.assertEqual(metrics["footprint_elements"]["0"],4)
        legacy=copy.deepcopy(data)
        for block in legacy["blocks"]:
            for direction in ("incoming","outgoing"):
                block[direction]=[e["block"] for e in block[direction]]
        self.grade("unsigned int f(unsigned char*p,unsigned int*q,unsigned int x){(void)q;unsigned int i=x&7u;return p[i<=3u?i:3u];}",reconstruct(legacy))
        # Wrong incoming-phi correspondence changes results on concrete inputs.
        wrong=copy.deepcopy(data)
        phi=next(o for o in wrong["operations"] if o["opcode"]=="MULTIEQUAL")
        phi["inputs"].reverse()
        # This input violates dominance (arm-local definitions on wrong edges).
        with self.assertRaises(Unsupported):reconstruct(wrong)

    def test_diamond_cannot_speculate_effects_or_accept_virtual_opcodes(self):
        data=byte_diamond()
        branch=data["operations"][data["blocks"][1]["operations"][0]]
        phi=next(o for o in data["operations"] if o["opcode"]=="MULTIEQUAL")
        phi["inputs"][0]=branch["inputs"][0]
        # Replace the false arm's copy with a store; its inputs dominate it.
        branch.update(opcode="STORE",inputs=[3,0,2]);branch.pop("output")
        with self.assertRaisesRegex(Unsupported,"effects"):reconstruct(data)
        data=byte_diamond();data["operations"][0]["opcode"]="CSRD_SELECT"
        with self.assertRaises(Unsupported):reconstruct(data)

    def test_stores_survive_constant_return_and_mutations(self):
        e = Export(); e.store(e.p, e.x); e.store(e.q, e.load(e.p))
        data = e.finish(e.constant(19))
        reference = "unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){p[0]=x;q[0]=p[0];return 19u;}"
        self.grade(reference, reconstruct(data))
        proof = self.grade(reference, reconstruct(data, store_offset=1), "counterexample")
        self.assertEqual(proof["proof"]["original_output"], proof["proof"]["candidate_output"])
        self.assertTrue(any(c["original"] != c["candidate"] for c in proof["proof"]["memory_cells"]))

    def test_last_store_control_avoids_cancelling_mutations(self):
        e = Export(); e.store(e.p, e.x)
        negated = e.op("INT_2COMP", [e.load(e.p)])
        e.store(e.p, negated); data = e.finish(e.constant(19))
        original = reconstruct(data)
        # Incrementing both stores cancels: -(x+1)+1 == -x.
        self.grade(original, reconstruct(data, store_offset=1))
        self.grade(original, reconstruct(data, final_store_offset=1), "counterexample")

    def test_pointer_offsets_copy_and_field_offsets(self):
        for opcode in ("PTRADD", "PTRSUB", "INT_ADD", "INT_SUB"):
            e = Export(readonly=True)
            args = [e.p, e.constant(15 if opcode == "PTRADD" else (60 if opcode != "INT_SUB" else (1 << 64)-60), 8)]
            if opcode == "PTRADD": args.append(e.constant(4, 8))
            pointer = e.op(opcode, args, size=8)
            pointer = e.op("COPY", [pointer], size=8)
            result = e.load(pointer)
            e.store(e.q, result)
            self.grade("unsigned int f(const unsigned int*p,unsigned int*q,unsigned int x){(void)x;q[0]=p[15];return p[15];}",
                       reconstruct(e.finish(result)))

    def test_scalar_canonicalization_inside_memory_contract(self):
        for code, constant, expression in (("INT_LEFT", 3, "x*8u"), ("INT_LEFT", 32, "0u"),
                                            ("INT_LEFT", 0xffffffffffffffff, "0u"),
                                            ("INT_NEGATE", None, "4294967295u-x"),
                                            ("INT_2COMP", None, "0u-x")):
            e = Export()
            inputs = [e.x] + ([] if constant is None else [e.constant(constant, 8)])
            result = e.op(code, inputs)
            e.store(e.p, result)
            self.grade(f"unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){{(void)q;p[0]={expression};return p[0];}}",
                       reconstruct(e.finish(result)))

    def test_32_bit_pointer_model(self):
        e = Export()
        pointer = e.op("PTRADD", [e.p, e.constant(15, 8), e.constant(4, 8)], size=8)
        e.store(pointer, e.x)
        data = e.finish(e.load(e.q))
        data["address_space"]["pointer_bytes"] = 4
        for node in data["nodes"]:
            if node["size"] == 8: node["size"] = 4
        self.grade("unsigned int f(unsigned int*p,unsigned int*q,unsigned int x){p[15]=x;return q[0];}", reconstruct(data))

    def test_reject_unknown_memory_and_malformed_graphs(self):
        changes = [
            lambda e: e.update(schema_version=3),
            lambda e: e["address_space"].update(addressable_unit_bytes=2),
            lambda e: e["address_space"].update(pointer_bytes=2),
            lambda e: e["address_space"].update(id=434),
            lambda e: e["parameters"][1].update(read_only=True),
            lambda e: e["nodes"][0].update(size=4),
            lambda e: e["nodes"][0].pop("parameter"),
            lambda e: e["nodes"][3].update(constant="-1"),
            lambda e: e["operations"][0].update(opcode="CALL"),
            lambda e: e["operations"][0].update(inputs=[999]),
            lambda e: e["operations"][0].update(output=0),
            lambda e: e["operations"][1].update(output=7),
            lambda e: e["operations"][1].update(inputs=[3, 2, 2]),
            lambda e: e["operations"][0].update(block=1),
            lambda e: e["blocks"][0].update(outgoing=[1]),
            lambda e: e["blocks"][0]["operations"].reverse(),
            lambda e: e["blocks"].append(copy.deepcopy(e["blocks"][0])),
            lambda e: e.update(operation_order="address-order"),
            lambda e: e["operations"].append(copy.deepcopy(e["operations"][-1])),
        ]
        for change in changes:
            data = snapshot(); change(data)
            with self.subTest(data=data), self.assertRaises(Unsupported): reconstruct(data)

    def test_reject_bad_offsets_widths_and_dynamic_addresses(self):
        for offset in (1, 64, (1 << 64)-4):
            e = Export()
            pointer = e.op("PTRSUB", [e.p, e.constant(offset, 8)], size=8)
            with self.assertRaises(Unsupported): reconstruct(e.finish(e.load(pointer)))
        e = Export(); pointer = e.op("PTRADD", [e.p, e.x, e.constant(4, 8)], size=8)
        with self.assertRaises(Unsupported): reconstruct(e.finish(e.load(pointer)))
        e = Export(); value = e.op("LOAD", [e.space, e.p], size=8)
        with self.assertRaises(Unsupported): reconstruct(e.finish(value))


if __name__ == "__main__":
    unittest.main()
