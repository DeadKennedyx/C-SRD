"""GDB-side bounded observation of registers, stack and a declared caller buffer.

Executed only against the controlled buffer_update harness. No anti-debugging
or observer interference; full snapshots remain evidence for later analysis.
"""
import collections
import json
from pathlib import Path
import re
import shlex
import gdb


class HeapTracker:
    """Observe standard allocator ABI boundaries, without source/encoding hints."""
    def __init__(self, entry, extent, aarch64):
        self.entry,self.extent,self.aarch64=entry,extent,aarch64
        self.objects={};self.events=[];self.errors=[];self.sequence=0;self.breakpoints=[];self.pending=False
        tracker=self
        class Returned(gdb.FinishBreakpoint):
            def __init__(self,kind,args):
                super().__init__(gdb.newest_frame(),internal=True)
                self.kind,self.args=kind,args;self.silent=True
            def stop(self):
                try:tracker.returned(self.kind,self.args,tracker.result())
                except Exception as error:tracker.errors.append(str(error))
                finally:tracker.pending=False
                return False
            def out_of_scope(self):
                tracker.pending=False;tracker.errors.append('allocator did not return normally')
        class Entered(gdb.Breakpoint):
            def __init__(self,name):
                super().__init__(name,internal=True);self.name=name;self.silent=True
            def stop(self):
                try:
                    ret=tracker.return_address()
                    if not tracker.entry<=ret<tracker.entry+tracker.extent:return False
                    # realloc(NULL,n) can tail-call malloc with the same return
                    # address. Observe the outer ABI event exactly once.
                    if tracker.pending:return False
                    args=tracker.arguments()
                    if self.name=='free':
                        tracker.release(args[0]);tracker.events.append({'kind':'free','null':args[0]==0})
                    else:tracker.pending=True;Returned(self.name,args)
                except Exception as error:tracker.pending=False;tracker.errors.append(str(error))
                return False
        self.breakpoints=[Entered(name) for name in ('malloc','calloc','realloc','free')]

    def arguments(self):
        names=('x0','x1') if self.aarch64 else ('rdi','rsi')
        return tuple(int(gdb.parse_and_eval('$'+name)) for name in names)

    def result(self):return int(gdb.parse_and_eval('$x0' if self.aarch64 else '$rax'))

    def return_address(self):
        if self.aarch64:return int(gdb.parse_and_eval('$x30'))
        sp=int(gdb.parse_and_eval('$sp'))
        return int.from_bytes(gdb.selected_inferior().read_memory(sp,8).tobytes(),'little')

    def release(self,address):
        if address:
            if address not in self.objects:raise ValueError('unobserved or non-base heap release')
            del self.objects[address]

    def returned(self,kind,args,address):
        size=args[0]*args[1] if kind=='calloc' else args[1] if kind=='realloc' else args[0]
        if size>128 or size%4:raise ValueError('heap observation extent outside admitted uint32 capacity')
        self.events.append({'kind':kind,'bytes':size,'success':bool(address)})
        if not address:return
        if kind=='realloc':self.release(args[0])
        if address in self.objects:raise ValueError('overlapping live allocation base')
        self.objects[address]=(self.sequence,size);self.sequence+=1

    def words(self):
        values={}
        for address,(object_id,size) in self.objects.items():
            try:
                raw=gdb.selected_inferior().read_memory(address,size).tobytes()
                values.update({f'heap:{object_id}:{i//4}':int.from_bytes(raw[i:i+4],'little') for i in range(0,size,4)})
            except gdb.MemoryError as error:self.errors.append(str(error))
        return values

    def close(self):
        for breakpoint in self.breakpoints:breakpoint.delete()


class StreamTracker(HeapTracker):
    """Observe real stdio ABI events at calls made by the selected activation."""
    def __init__(self,entry,extent,aarch64,memory_address):
        self.entry,self.extent,self.aarch64=entry,extent,aarch64
        self.memory_address=memory_address;self.events=[];self.errors=[];self.pending=False
        self.handles=[int(gdb.parse_and_eval('*(unsigned long*)&'+n)) for n in ('csrd_input','csrd_output')]
        tracker=self
        class Returned(gdb.FinishBreakpoint):
            def __init__(self,event):
                super().__init__(gdb.newest_frame(),internal=True);self.event=event;self.silent=True
            def stop(self):
                try:
                    self.event[3]=0 if self.event[0]==6 else tracker.result()&0xffffffff
                    tracker.events.append(self.event)
                except Exception as error:tracker.errors.append(str(error))
                finally:tracker.pending=False
                return False
            def out_of_scope(self):tracker.pending=False;tracker.errors.append('stdio call did not return normally')
        class Entered(gdb.Breakpoint):
            def __init__(self,name,kind):
                super().__init__(name,internal=True);self.kind=kind;self.silent=True
            def stop(self):
                try:
                    ret=tracker.return_address()
                    if not tracker.entry<=ret<tracker.entry+tracker.extent or tracker.pending:return False
                    args=tracker.arguments();handle=args[1] if self.kind==2 else args[0]
                    stream=tracker.handles.index(handle)
                    raw=gdb.selected_inferior().read_memory(tracker.memory_address,64*4).tobytes()
                    event=[self.kind,stream,args[0]&0xffffffff if self.kind==2 else 0,0,
                           *[int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw),4)]]
                    tracker.pending=True;Returned(event)
                except Exception as error:tracker.pending=False;tracker.errors.append(str(error))
                return False
        self.breakpoints=[Entered(name,i+1) for i,name in enumerate(('fgetc','fputc','fflush','feof','ferror','clearerr'))]


def collect(config):
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    gdb.execute("set disable-randomization off")
    gdb.execute("set print thread-events off")
    # Starting at main loads the shared library before resolving its symbol.
    gdb.execute("start < " + shlex.quote(config["input_file"]))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", config["function"]):
        raise ValueError("invalid function symbol")
    gdb.Breakpoint("*" + config["function"], temporary=True)
    gdb.execute("continue", to_string=True)
    architecture = gdb.selected_frame().architecture().name()
    if "aarch64" in architecture:
        registers = [f"x{i}" for i in range(31)]
        return_address = int(gdb.parse_and_eval("$x30"))
    elif "x86-64" in architecture:
        registers = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp",
                     "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
        sp = int(gdb.parse_and_eval("$sp"))
        return_address = int.from_bytes(gdb.selected_inferior().read_memory(sp, 8).tobytes(), "little")
    else:
        raise RuntimeError("observer requires AArch64 or x86-64")
    if "little endian" not in gdb.execute("show endian", to_string=True):
        raise RuntimeError("observer requires little-endian target")
    memory_address = int(gdb.parse_and_eval("(unsigned long)&csrd_observation_memory"))
    globals_=[]
    for name,size in config.get("persistent_objects",{}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*",name) or size not in (4,8):raise ValueError("invalid persistent observation extent")
        globals_.append((name,int(gdb.parse_and_eval("(unsigned long)&"+name)),size))
    def global_words():
        words={}
        for name,at,size in globals_:
            raw=gdb.selected_inferior().read_memory(at,size).tobytes()
            words.update({f"global:{name}:{i//4}":int.from_bytes(raw[i:i+4],"little") for i in range(0,size,4)})
        return words
    entry = int(gdb.parse_and_eval("$pc"))
    call_scope = config.get("call_scope",False)
    function_bytes = config.get("function_bytes",0)
    if call_scope and (type(function_bytes) is not int or function_bytes<1):raise ValueError("missing function extent")
    heap=HeapTracker(entry,function_bytes,'aarch64' in architecture) if config.get('observe_heap') else None
    streams=StreamTracker(entry,function_bytes,'aarch64' in architecture,memory_address) if config.get('observe_stdio') else None
    tail_transfers=0
    visits, samples, failures = collections.Counter(), [], 0
    for _ in range(config["step_limit"]):
        pc = int(gdb.parse_and_eval("$pc"))
        if pc == return_address: break
        if call_scope and not entry<=pc<entry+function_bytes:
            # A tail transfer leaves the caller permanently under this corpus's
            # no-reentry contract. Do not mix ASLR-dependent external PCs into
            # the caller's location-fitting task.
            gdb.Breakpoint("*"+str(return_address),temporary=True)
            gdb.execute("continue",to_string=True);tail_transfers+=1;break
        offset = pc - entry; visit = visits[offset]; visits[offset] += 1
        values = {"reg:" + name: int(gdb.parse_and_eval("$" + name)) & 0xffffffff for name in registers}
        memory = gdb.selected_inferior().read_memory(memory_address, 64*4).tobytes()
        values.update({f"caller:{i}": int.from_bytes(memory[4*i:4*i+4], "little") for i in range(64)})
        values.update(global_words())
        if heap:values.update(heap.words())
        if config.get("sample_bytes"):
            values.update({f"caller-byte:{i}":value for i,value in enumerate(memory)})
        try:
            sp = int(gdb.parse_and_eval("$sp"))
            stack = gdb.selected_inferior().read_memory(sp, 64).tobytes()
            values.update({f"stack+{i}": int.from_bytes(stack[i:i+4], "little") for i in range(0, 64, 4)})
        except gdb.MemoryError:
            failures += 1
        samples.append({"offset": offset, "visit": visit, "values": values})
        gdb.execute("nexti" if call_scope else "stepi", to_string=True)
    complete = int(gdb.parse_and_eval("$pc")) == return_address
    result = {"status": "completed" if complete else "step-limit", "architecture": architecture,
              "samples": samples, "steps": len(samples), "stack_read_failures": failures,
              "scope": "low32 general registers, 64 bytes at SP, all64 caller words before each instruction; no SIMD coverage" +
                       ("; all256 caller bytes also sampled" if config.get("sample_bytes") else "")}
    if call_scope:
        result.update(tail_transfers_skipped=tail_transfers,
                      call_observation_scope="caller instructions only; nexti steps over callees; tail transfers run to caller return; callee interiors unmeasured")
    if heap:
        result.update(heap_events=heap.events,heap_observer_errors=heap.errors,heap_live_objects_at_return=len(heap.objects))
        result['scope']+='; all words of live owned allocations at caller instruction boundaries, including uninitialized bytes; allocator ABI breakpoints supply addresses/extents only'
        heap.close()
    if streams:
        if streams.pending or tail_transfers:streams.errors.append('unobserved stdio return or tail transfer')
        result.update(stdio_events=streams.events,stdio_observer_errors=streams.errors)
        result['scope']+='; ordered real stdio ABI calls from root, including pre-call user memory and results; library interiors unmeasured'
        streams.close()
    if complete:
        memory = gdb.selected_inferior().read_memory(memory_address, 64*4).tobytes()
        result["final_memory"] = [int.from_bytes(memory[4*i:4*i+4], "little") for i in range(64)]
        result["return_value"] = int(gdb.parse_and_eval("$x0" if "aarch64" in architecture else "$rax")) & 0xffffffff
        if globals_:
            result["persistent_state"]=list(global_words().values())
            result["scope"]+="; declared persistent globals sampled before every instruction and at return"
        if call_scope and config.get('observe_call_events',True):
            def word_symbol(name):
                at=int(gdb.parse_and_eval("(unsigned long)&"+name))
                return int.from_bytes(gdb.selected_inferior().read_memory(at,4).tobytes(),"little")
            count=word_symbol("event_count")
            if count>8:raise ValueError("call event budget exceeded")
            at=int(gdb.parse_and_eval("(unsigned long)&events"))
            raw=gdb.selected_inferior().read_memory(at,count*69*4).tobytes() if count else b""
            result["external_state"]=word_symbol("external_state")
            result["events"]=[[int.from_bytes(raw[(i*69+j)*4:(i*69+j+1)*4],"little") for j in range(69)] for i in range(count)]
        if streams:
            gdb.Breakpoint('*csrd_snapshot_marker',temporary=True)
            gdb.execute('continue',to_string=True)
            at=int(gdb.parse_and_eval('(unsigned long)&csrd_stream_observation'))
            raw=gdb.selected_inferior().read_memory(at,139*4).tobytes()
            result['stdio_state']=[int.from_bytes(raw[i:i+4],'little') for i in range(0,len(raw),4)]
        gdb.execute("continue", to_string=True)
    return result


def main(config_path):
    config = json.loads(Path(config_path).read_text())
    try:
        result = collect(config)
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    Path(config["output"]).write_text(json.dumps(result, indent=2) + "\n")
    gdb.execute("quit")
