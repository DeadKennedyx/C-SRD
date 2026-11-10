"""Persistent Ghidra and adapter sessions, measured by an external collector."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

from effort_resources import save
from process_counters import Phase, family, process
from pcode_reconstruct import reconstruct

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def receive(stream):
    line = stream.readline(4*1024*1024+1)
    if not line or len(line)>4*1024*1024:
        raise ValueError("missing or oversized session event")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("session event must be an object")
    return value


def descendant(pid, ancestor):
    visited = set()
    while pid>1 and pid not in visited:
        if pid==ancestor: return True
        visited.add(pid); pid=process(pid)["parent"]
    return False


def events(server, token, role, child, output, deadline, expected):
    server.settimeout(max(0.1, deadline-time.monotonic()))
    connection, _ = server.accept()
    connection.settimeout(max(0.1, deadline-time.monotonic()))
    rows, active, name = [], None, None
    with connection, connection.makefile("rwb", buffering=0) as stream:
        hello = receive(stream)
        data = hello.get("payload", {})
        pid = data.get("pid")
        if (hello.get("event")!="hello" or data.get("token")!=token or data.get("role")!=role or
                type(pid) is not int or not descendant(pid, child.pid)):
            raise ValueError("unowned or invalid session peer")
        stream.write(b"ok\n")
        try:
            for expected_name, stable, count in expected:
                event = receive(stream)
                if event.get("event")!="begin" or event.get("phase")!=expected_name or event.get("stable") is not stable:
                    raise ValueError("unexpected, duplicated or reordered phase")
                name=expected_name
                if stable:
                    members=family(pid,role)
                    labels=[p["role"] for p in members.values()]
                    if sorted(labels)!=sorted([role]+(["native"] if role=="jvm" else [])):
                        raise ValueError("unexpected process family at measured boundary")
                active=Phase(pid,role,stable=stable)
                stream.write(b"ok\n")
                event=receive(stream)
                result=active.finish(); active=None
                payload=event.get("payload")
                if (event.get("event")!="end" or event.get("phase")!=name or event.get("stable") is not stable or
                        not isinstance(payload,dict) or (count is not None and payload.get("requests")!=count)):
                    raise ValueError("phase end/count mismatch")
                rows.append({"phase":name,"resources":result,"result":payload})
                save(output, {"status":"running","role":role,"pid":pid,"phases":rows})
                stream.write(b"ok\n")
            done=receive(stream)
            if done.get("event")!="done":
                raise ValueError("unexpected extra session event")
            stream.write(b"ok\n")
        finally:
            if active is not None:
                rows.append({"phase":name,"resources":active.finish(),"error":"incomplete phase"})
                save(output,{"status":"failed","role":role,"pid":pid,"phases":rows})
    result={"status":"completed" if all(r["resources"]["status"]=="completed" for r in rows) else "invalid-counters",
            "role":role,"pid":pid,"phases":rows}
    save(output,result)
    return result


def serve(config, directory, role, command, expected):
    token=secrets.token_hex(16)
    with socket.socket() as server:
        server.bind(("127.0.0.1",0));server.listen(1)
        settings={**config,"port":server.getsockname()[1],"token":token,"output":str(directory)}
        path=directory/(role+"-config.json");save(path,settings)
        argv=command(path)
        save(directory/(role+"-command.json"),{"argv":list(map(str,argv))})
        with (directory/(role+"-stdout.txt")).open("wb") as stdout, (directory/(role+"-stderr.txt")).open("wb") as stderr:
            child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+config["session_seconds"]
                result=events(server,token,role,child,directory/(role+"-phases.json"),deadline,expected)
                code=child.wait(timeout=max(0.1,deadline-time.monotonic()))
                if code:raise ValueError(f"{role} session exited {code}")
                if result["status"]!="completed":raise ValueError("invalid process counters")
                return result
            finally:
                if child.poll() is None:
                    # The enclosing resource collector owns descendant cleanup.
                    child.terminate()
                    try:child.wait(timeout=3)
                    except subprocess.TimeoutExpired:child.kill();child.wait()


def worker(config, directory):
    project=directory/"project";project.mkdir()
    expected=[("setup",False,None),("first",True,1)]
    if config["warmup_calls"]>1:expected.append(("warmup",True,config["warmup_calls"]-1))
    expected.append(("empty",True,0))
    expected += [(f"batch-{i}",True,config["calls"]) for i in range(config["batches"])]
    def command(path):
        return [config["headless"],str(project),"session","-import",config["binary"],"-deleteProject","-max-cpu","2",
                "-analysisTimeoutPerFile",str(config["analysis_seconds"]),"-scriptPath",str(ROOT/"tools/ghidra"),
                "-postScript","SessionCSRD.java",str(path)]
    native=serve(config,directory,"jvm",command,expected)
    # Validate every retained export and every request membership before replay.
    for phase in native["phases"]:
        result=phase["result"]
        if phase["phase"]=="setup":continue
        if not (len(result["exports"])==len(result["decompile_ns"])==len(result["flush_ns"])==result["requests"]):
            raise ValueError("missing native request evidence")
        for sha in result["exports"]:
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha):
                raise ValueError("invalid export hash")
            if digest((directory/"exports"/(sha+".json")).read_bytes())!=sha:
                raise ValueError("export content changed")
    adapter_expected=[(name,True,count) for name,stable,count in expected if name!="setup"]
    adapter=serve(config,directory,"adapter",lambda path:[sys.executable,__file__,"--adapter",str(path)],adapter_expected)
    return {"status":"completed","jvm":native,"adapter":adapter}


def adapter(config):
    root=Path(config["output"])
    native=json.loads((root/"jvm-phases.json").read_text())
    exports={p.stem:json.loads(p.read_text()) for p in (root/"exports").glob("*.json")}
    (root/"answers").mkdir()
    with socket.create_connection(("127.0.0.1",config["port"])) as connection, connection.makefile("rwb",buffering=0) as stream:
        connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        def event(kind,phase,payload=None):
            stream.write((json.dumps({"event":kind,"phase":phase,"stable":True,"payload":payload})+"\n").encode())
            if stream.readline()!=b"ok\n":raise ValueError("adapter phase not acknowledged")
        event("hello","hello",{"token":config["token"],"role":"adapter","pid":os.getpid()})
        saved=set()
        for phase in native["phases"]:
            name=phase["phase"]
            if name=="setup":continue
            event("begin",name)
            answers,metrics,wall=[],[],[]
            for sha in phase["result"]["exports"]:
                row={};start=time.perf_counter_ns()
                source=reconstruct(exports[sha],metrics=row).encode()
                wall.append(time.perf_counter_ns()-start)
                value=digest(source)
                if value not in saved:
                    (root/"answers"/(value+".c")).write_bytes(source);saved.add(value)
                answers.append({"export_sha256":sha,"candidate_sha256":value});metrics.append(row)
            event("end",name,{"requests":len(answers),"answers":answers,"metrics":metrics,"reconstruct_ns":wall})
        event("done","done",{})


if __name__=="__main__":
    if sys.argv[1]=="--adapter":
        adapter(json.loads(Path(sys.argv[2]).read_text()))
    else:
        path=Path(sys.argv[1]).resolve();config=json.loads(path.read_text())
        try:
            result=worker(config,path.parent)
        except Exception as error:
            save(path.parent/"session.json",{"status":"failed","error":str(error)})
            raise
        save(path.parent/"session.json",result)
