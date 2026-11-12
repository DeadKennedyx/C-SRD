"""Flatten scalar branch diamonds without moving a load, store or call.

SSA dominance and reciprocal edges are checked by the existing CFG validator.
Only total P-code scalar operations may be speculated. Memory effects remain on
one ordered path; loops, nested diamonds and branch-local effects fail closed.
"""
from pcode_cfg import Graph, CONTROL, LIMITS, index
from pcode_values import SCALAR, Unsupported


def validated_graph(export):
    nodes,ops=export["nodes"],export["operations"]
    if not isinstance(nodes,list) or not isinstance(ops,list) or len(nodes)>LIMITS["nodes"] or len(ops)>LIMITS["operations"]:
        raise Unsupported("invalid memory CFG or graph budget exceeded")
    records=export["blocks"]
    if not isinstance(records,list):raise Unsupported("invalid block records")
    edges=[e for b in records for key in ("incoming","outgoing") for e in b[key]]
    if any(type(e) is int for e in edges):
        if any(type(e) is not int for e in edges):raise Unsupported("mixed legacy and indexed CFG edges")
        by_id={b["id"]:b for b in records}
        if len(by_id)!=len(records):raise Unsupported("duplicate legacy block id")
        normalized=[]
        for block in records:
            value=dict(block)
            for direction,reverse in (("incoming","outgoing"),("outgoing","incoming")):
                value[direction]=[]
                for other in block[direction]:
                    if other not in by_id:raise Unsupported("unknown legacy edge endpoint")
                    peers=by_id[other][reverse]
                    if peers.count(block["id"])!=1 or block[direction].count(other)!=1:
                        raise Unsupported("legacy parallel CFG edges lack unambiguous phi order")
                    value[direction].append({"block":other,"reverse_index":peers.index(block["id"])})
            normalized.append(value)
        export={**export,"blocks":normalized}
    graph=Graph.__new__(Graph)
    graph.nodes,graph.ops=nodes,ops
    graph.initial={i:None for i,n in enumerate(nodes) if "constant" in n or "parameter" in n or (n.get("input") and "linkage_pointer" in n)}
    graph.definitions={}
    for oi,op in enumerate(ops):
        code=op["opcode"]
        calls={"CALL"} if (export.get("schema_version"),export.get("memory_model")) in ((7,"ordered-calls-buffers-v1"),(8,"records-state-buffers-v1")) else set()
        extra={"INDIRECT"} if export.get("schema_version")==8 else set()
        if code not in SCALAR|CONTROL|{"LOAD","STORE","PTRADD","PTRSUB","MULTIEQUAL"}|calls|extra:
            raise Unsupported("unsupported memory CFG instruction: "+code)
        if not isinstance(op["inputs"],list):raise Unsupported("invalid CFG instruction inputs")
        for value in op["inputs"]:index(value,len(nodes),"varnode")
        if "output" in op:
            out=index(op["output"],len(nodes),"varnode")
            if out in graph.initial or out in graph.definitions or nodes[out].get("input"):
                raise Unsupported("duplicate CFG definition or overwrite of input")
            graph.definitions[out]=oi
        if code in CONTROL:
            if "output" in op or len(op["inputs"])!=(1 if code=="BRANCH" else 2):
                raise Unsupported("invalid CFG terminator")
            if code=="CBRANCH" and graph.width(op["inputs"][1])!=8:
                raise Unsupported("branch condition must be byte")
    graph.cfg(export)
    return graph


def linearize(export):
    graph=validated_graph(export)
    ops=graph.ops
    seen,flat=set(),[]

    def append(op):
        flat.append({**op,"block":0})

    def arm(edge):
        chain=[];visited=set()
        while True:
            bid=edge["block"];block=graph.blocks[bid]
            if bid in visited:raise Unsupported("cyclic memory CFG")
            visited.add(bid)
            if len(block["incoming"])!=1:return chain,bid,edge["reverse_index"]
            if len(block["outgoing"])!=1:raise Unsupported("nested branch or return inside scalar diamond")
            for oi in block["operations"]:
                if ops[oi]["opcode"] not in SCALAR|{"BRANCH"}:
                    raise Unsupported("memory effects or merges inside a branch cannot be speculated")
            chain.append(bid);edge=block["outgoing"][0]

    bid=graph.entry;skip_phi=False;diamonds=0
    while True:
        if bid in seen:raise Unsupported("cyclic or overlapping memory CFG")
        seen.add(bid);block=graph.blocks[bid]
        body=[ops[i] for i in block["operations"]]
        for op in body:
            if op["opcode"]=="MULTIEQUAL":
                if not skip_phi:raise Unsupported("unexpected scalar merge")
            elif op["opcode"] not in ("BRANCH","CBRANCH"):append(op)
        skip_phi=False
        if not block["outgoing"]:break
        if len(block["outgoing"])==1:
            bid=block["outgoing"][0]["block"];continue
        no,join,no_slot=arm(block["outgoing"][0])
        yes,other,yes_slot=arm(block["outgoing"][1])
        if join!=other or no_slot==yes_slot or len(graph.blocks[join]["incoming"])!=2:
            raise Unsupported("requires a two-arm scalar diamond with one join")
        condition=body[-1]["inputs"][1]
        for branch in (no,yes):
            for bb in branch:
                if bb in seen:raise Unsupported("overlapping scalar diamond arms")
                seen.add(bb)
                for oi in graph.blocks[bb]["operations"]:
                    if ops[oi]["opcode"]!="BRANCH":append(ops[oi])
        for oi in graph.blocks[join]["operations"]:
            phi=ops[oi]
            if phi["opcode"]!="MULTIEQUAL":continue
            bits=graph.width(phi["output"])
            if bits not in (8,16,32,64) or any(graph.width(i)!=bits for i in phi["inputs"]):
                raise Unsupported("inconsistent scalar merge widths")
            # This opcode is internal. Raw exports containing it were rejected.
            append({"opcode":"CSRD_SELECT","output":phi["output"],
                    "inputs":[condition,phi["inputs"][yes_slot],phi["inputs"][no_slot]]})
        diamonds+=1;bid=join;skip_phi=True
    if seen!=graph.blocks.keys():raise Unsupported("unhandled memory CFG blocks")
    return flat,diamonds
