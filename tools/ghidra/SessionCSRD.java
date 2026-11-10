// Persistent analysis of one unchanged binary; original source is never supplied.
// @category C-SRD
import ghidra.app.util.headless.HeadlessScript;
import ghidra.app.decompiler.*;
import ghidra.framework.Application;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.UnsignedIntegerDataType;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.pcode.*;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.mem.MemoryBlock;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.net.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

public class SessionCSRD extends HeadlessScript {
    private final Gson gson = new GsonBuilder().setPrettyPrinting().create();
    private BufferedReader input;
    private BufferedWriter output;
    private Path destination;
    private String function;
    private int arity, timeout;
    private DecompInterface decompiler;
    private Function target;
    private final Set<String> saved = new HashSet<>();

    private void event(String kind, String phase, boolean stable, JsonObject payload) throws Exception {
        JsonObject message = new JsonObject();
        message.addProperty("event", kind); message.addProperty("phase", phase);
        message.addProperty("stable", stable);
        if (payload != null) message.add("payload", payload);
        output.write(new Gson().toJson(message)); output.newLine(); output.flush();
        if (!"ok".equals(input.readLine())) throw new IOException("collector did not acknowledge phase");
    }
    private static String hash(String text) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
    }
    private JsonObject metadata() {
        JsonObject report = new JsonObject();
        report.addProperty("schema_version", 3);
        report.addProperty("memory_model", "immutable-mapped-constants-v1");
        report.addProperty("ghidra_version", Application.getApplicationVersion());
        report.addProperty("language", currentProgram.getLanguageID().toString());
        report.addProperty("compiler_spec", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        report.addProperty("function", function); report.addProperty("arity", arity);
        report.addProperty("entry", target.getEntryPoint().toString());
        return report;
    }
    private void batch(String phase, int count, boolean empty) throws Exception {
        event("begin", phase, true, null);
        JsonArray hashes = new JsonArray(), decompileNs = new JsonArray(), flushNs = new JsonArray();
        for (int i=0; i<count; ++i) {
            if (empty) continue;
            long beforeFlush = System.nanoTime();
            decompiler.flushCache();
            flushNs.add(System.nanoTime()-beforeFlush);
            long start = System.nanoTime();
            DecompileResults result = decompiler.decompileFunction(target, timeout, monitor);
            decompileNs.add(System.nanoTime()-start);
            if (!result.decompileCompleted()) throw new IOException("decompile failed: " + result.getErrorMessage());
            JsonObject report = metadata();
            new SessionGraph().fill(result, target, currentProgram, report);
            String text = gson.toJson(report), digest = hash(text);
            if (saved.add(digest)) {
                Files.writeString(destination.resolve("exports").resolve(digest+".json"), text);
                Files.writeString(destination.resolve("exports").resolve(digest+".c"), result.getDecompiledFunction().getC());
            }
            hashes.add(digest);
        }
        JsonObject payload = new JsonObject();
        payload.addProperty("requests", empty ? 0 : count);
        payload.add("exports", hashes); payload.add("decompile_ns", decompileNs); payload.add("flush_ns", flushNs);
        event("end", phase, true, payload);
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("session-config.json required");
        JsonObject config = JsonParser.parseString(Files.readString(Paths.get(args[0]))).getAsJsonObject();
        destination=Paths.get(config.get("output").getAsString());
        function=config.get("function").getAsString(); arity=config.get("arity").getAsInt();
        timeout=config.get("decompile_seconds").getAsInt();
        if (!function.matches("[A-Za-z_][A-Za-z_0-9]*") || arity<1 || arity>4 || timeout<1 || timeout>60)
            throw new IllegalArgumentException("invalid public interface or deadline");
        int warmup=config.get("warmup_calls").getAsInt(), calls=config.get("calls").getAsInt(), batches=config.get("batches").getAsInt();
        if(warmup<1 || warmup>1024 || calls<1 || calls>1024 || batches<1 || batches>100)
            throw new IllegalArgumentException("invalid bounded batch sizes");
        Files.createDirectories(destination.resolve("exports"));
        try (Socket socket = new Socket(InetAddress.getByName("127.0.0.1"), config.get("port").getAsInt())) {
            socket.setTcpNoDelay(true);
            input=new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
            output=new BufferedWriter(new OutputStreamWriter(socket.getOutputStream(), StandardCharsets.UTF_8));
            JsonObject hello=new JsonObject(); hello.addProperty("pid", ProcessHandle.current().pid());
            hello.addProperty("role", "jvm"); hello.addProperty("token", config.get("token").getAsString());
            event("hello", "hello", false, hello);
            event("begin", "setup", false, null);
            if (analysisTimeoutOccurred()) throw new IOException("Ghidra analysis timeout");
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (f.getName().equals(function) || f.getName().equals("_"+function)) {
                    if(target!=null) throw new IllegalStateException("ambiguous function symbol");
                    target=f;
                }
            }
            if(target==null) throw new IllegalStateException("missing function");
            List<Variable> parameters=new ArrayList<>();
            for(int i=0;i<arity;++i) parameters.add(new ParameterImpl("p"+i, UnsignedIntegerDataType.dataType, currentProgram));
            target.setReturnType(UnsignedIntegerDataType.dataType, SourceType.USER_DEFINED);
            target.replaceParameters(parameters, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.USER_DEFINED);
            target.setVarArgs(false);
            decompiler=new DecompInterface();
            decompiler.setSimplificationStyle("decompile"); decompiler.toggleCCode(true); decompiler.toggleSyntaxTree(true);
            if(!decompiler.openProgram(currentProgram)) throw new IOException(decompiler.getLastMessage());
            event("end", "setup", false, new JsonObject());
            batch("first", 1, false);
            if(warmup>1) batch("warmup", warmup-1, false);
            batch("empty", calls, true);
            for(int i=0;i<batches;++i) batch("batch-"+i, calls, false);
            event("done", "done", true, new JsonObject());
        } finally {
            if(decompiler!=null) decompiler.dispose();
        }
    }
}

// The marked graph block is byte-identical to ExportCSRD.java. Tests enforce
// that correspondence; this experimental session does not add semantic rules.
class SessionGraph {
    private final IdentityHashMap<Varnode, Integer> ids = new IdentityHashMap<>();
    private final List<Varnode> nodes = new ArrayList<>();
    private int id(Varnode node) {
        if (!ids.containsKey(node)) { ids.put(node, nodes.size()); nodes.add(node); }
        return ids.get(node);
    }
    void fill(DecompileResults result, Function target, Program currentProgram, JsonObject report) throws Exception {
            HighFunction high = result.getHighFunction();
            JsonArray operations = new JsonArray();
            JsonObject userops = new JsonObject();
            JsonArray blocks = new JsonArray();
            Integer entryBlock = null;
            // getPcodeOps() is sequence/address order and includes dead ops.
            // The block iterator supplies actual instruction order. Edge slots
            // retain phi associations, including parallel edges to one block.
            for (PcodeBlockBasic block : high.getBasicBlocks()) {
                JsonObject descriptor = new JsonObject();
                descriptor.addProperty("id", block.getIndex());
                descriptor.addProperty("start", block.getStart().toString());
                if (block.contains(target.getEntryPoint())) {
                    if (entryBlock != null) throw new IllegalStateException("ambiguous entry block");
                    entryBlock = block.getIndex();
                }
                JsonArray incoming = new JsonArray(), outgoing = new JsonArray(), ordered = new JsonArray();
                for (int i = 0; i < block.getInSize(); ++i) {
                    JsonObject edge = new JsonObject();
                    edge.addProperty("block", block.getIn(i).getIndex());
                    edge.addProperty("reverse_index", block.getInRevIndex(i));
                    incoming.add(edge);
                }
                for (int i = 0; i < block.getOutSize(); ++i) {
                    JsonObject edge = new JsonObject();
                    edge.addProperty("block", block.getOut(i).getIndex());
                    edge.addProperty("reverse_index", block.getOutRevIndex(i));
                    outgoing.add(edge);
                }
                Iterator<PcodeOp> iterator = block.getIterator();
                while (iterator.hasNext()) {
                    PcodeOp op = iterator.next();
                    JsonObject item = new JsonObject();
                    item.addProperty("opcode", op.getMnemonic());
                    item.addProperty("address", op.getSeqnum().getTarget().toString());
                    item.addProperty("block", block.getIndex());
                    if (op.getOpcode() == PcodeOp.CALLOTHER && op.getNumInputs() > 0 && op.getInput(0).isConstant()) {
                        long number = op.getInput(0).getOffset();
                        if (number >= 0 && number <= Integer.MAX_VALUE) {
                            String name = currentProgram.getLanguage().getUserDefinedOpName((int)number);
                            if (name != null) userops.addProperty(Long.toString(number), name);
                        }
                    }
                    if (op.getOutput() != null) item.addProperty("output", id(op.getOutput()));
                    JsonArray inputs = new JsonArray();
                    for (int i = 0; i < op.getNumInputs(); ++i) inputs.add(id(op.getInput(i)));
                    item.add("inputs", inputs);
                    ordered.add(operations.size()); operations.add(item);
                }
                descriptor.add("incoming", incoming); descriptor.add("outgoing", outgoing);
                descriptor.add("operations", ordered); blocks.add(descriptor);
            }
            if (entryBlock == null) throw new IllegalStateException("missing entry block");
            report.addProperty("entry_block", entryBlock);
            report.addProperty("operation_order", "basic-block-live-order");
            report.add("blocks", blocks);
            JsonArray variables = new JsonArray();
            for (Varnode node : nodes) {
                JsonObject item = new JsonObject();
                item.addProperty("size", node.getSize());
                item.addProperty("input", node.isInput());
                item.addProperty("storage", node.getAddress().toString());
                if (node.isConstant()) item.addProperty("constant", Long.toUnsignedString(node.getOffset()));
                if (node.isInput() && node instanceof VarnodeAST && ((VarnodeAST)node).getHigh() instanceof HighParam)
                    item.addProperty("parameter", ((HighParam)((VarnodeAST)node).getHigh()).getSlot());
                if (node.isInput() && !item.has("parameter")) {
                    JsonObject diagnostic = new JsonObject();
                    diagnostic.addProperty("space", node.getAddress().getAddressSpace().getName());
                    diagnostic.addProperty("default_space", currentProgram.getAddressFactory().getDefaultAddressSpace().getName());
                    MemoryBlock found = currentProgram.getMemory().getBlock(node.getAddress());
                    if (found != null) {
                        diagnostic.addProperty("block", found.getName());
                        diagnostic.addProperty("read", found.isRead()); diagnostic.addProperty("write", found.isWrite());
                        diagnostic.addProperty("execute", found.isExecute()); diagnostic.addProperty("initialized", found.isInitialized());
                        diagnostic.addProperty("relocations", currentProgram.getRelocationTable().getRelocations(new AddressSet(node.getAddress(), node.getAddress().addNoWrap(node.getSize()-1))).hasNext());
                    }
                    item.add("memory_diagnostic", diagnostic);
                }
                if (node.isInput() && !item.has("parameter") && !node.isConstant() && node.getSize() >= 1 && node.getSize() <= 16 &&
                    node.getAddress().getAddressSpace().equals(currentProgram.getAddressFactory().getDefaultAddressSpace())) {
                    MemoryBlock block = currentProgram.getMemory().getBlock(node.getAddress());
                    var end = node.getAddress().addNoWrap(node.getSize()-1);
                    if (block != null && block.contains(end) && block.isRead() && !block.isWrite() &&
                        block.isInitialized() &&
                        !currentProgram.getRelocationTable().getRelocations(new AddressSet(node.getAddress(), end)).hasNext()) {
                        byte[] bytes = new byte[node.getSize()];
                        if (currentProgram.getMemory().getBytes(node.getAddress(), bytes) != bytes.length)
                            throw new IllegalStateException("incomplete read-only constant");
                        StringBuilder hex = new StringBuilder();
                        for (byte value : bytes) hex.append(String.format("%02x", value & 255));
                        JsonObject snapshot = new JsonObject();
                        snapshot.addProperty("bytes_hex", hex.toString());
                        snapshot.addProperty("byte_order", currentProgram.getLanguage().isBigEndian() ? "big" : "little");
                        snapshot.addProperty("address", node.getAddress().toString());
                        snapshot.addProperty("block_start", block.getStart().toString());
                        snapshot.addProperty("block_end", block.getEnd().toString());
                        snapshot.addProperty("read", true); snapshot.addProperty("write", false);
                        snapshot.addProperty("execute", block.isExecute()); snapshot.addProperty("initialized", true);
                        snapshot.addProperty("relocations", false);
                        item.add("readonly", snapshot);
                    }
                }
                variables.add(item);
            }
            report.add("nodes", variables);
            report.add("operations", operations);
            report.add("userops", userops);
            report.addProperty("status", "decompiled");
    }
}
