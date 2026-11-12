// Export only binary semantics and a caller-supplied public buffer ABI.
// @category C-SRD
import ghidra.app.util.headless.HeadlessScript;
import ghidra.app.decompiler.*;
import ghidra.framework.Application;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.pcode.*;
import ghidra.program.model.address.AddressSpace;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

public class ExportCSRDBuffers extends HeadlessScript {
    private final IdentityHashMap<Varnode, Integer> ids = new IdentityHashMap<>();
    private final List<Varnode> nodes = new ArrayList<>();
    private int id(Varnode node) {
        if (!ids.containsKey(node)) { ids.put(node, nodes.size()); nodes.add(node); }
        return ids.get(node);
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 4) throw new IllegalArgumentException("function public-buffer-ABI timeout-seconds output-directory");
        Path out = Paths.get(args[3]);
        JsonObject report = new JsonObject();
        report.addProperty("schema_version", 5);
        report.addProperty("memory_model", "ordered-byte-buffers-v2");
        report.addProperty("ghidra_version", Application.getApplicationVersion());
        report.addProperty("language", currentProgram.getLanguageID().toString());
        report.addProperty("compiler_spec", currentProgram.getCompilerSpec().getCompilerSpecID().toString());
        report.addProperty("function", args[0]);
        String[] abi = args[1].split(",", -1);
        if (abi.length < 1 || abi.length > 8) throw new IllegalArgumentException("one to eight parameters required");
        report.addProperty("arity", abi.length);
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        JsonObject memory = new JsonObject();
        memory.addProperty("id", Integer.toUnsignedLong(space.getSpaceID()));
        memory.addProperty("name", space.getName());
        memory.addProperty("pointer_bytes", currentProgram.getDefaultPointerSize());
        memory.addProperty("addressable_unit_bytes", space.getAddressableUnitSize());
        report.add("address_space", memory);
        DecompInterface decompiler = new DecompInterface();
        long start = System.nanoTime();
        try {
            if (analysisTimeoutOccurred()) { report.addProperty("status", "analysis-timeout"); return; }
            Function target = null;
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                if (f.getName().equals(args[0]) || f.getName().equals("_" + args[0])) {
                    if (target != null) throw new IllegalStateException("ambiguous function symbol");
                    target = f;
                }
            }
            if (target == null) { report.addProperty("status", "missing-function"); return; }
            report.addProperty("entry", target.getEntryPoint().toString());
            List<Variable> parameters = new ArrayList<>();
            JsonArray signature = new JsonArray();
            for (int i = 0; i < abi.length; ++i) {
                if (!Set.of("u", "p", "c", "b", "B", "s", "S", "h", "H", "j", "J").contains(abi[i]))
                    throw new IllegalArgumentException("unknown ABI type");
                DataType type = UnsignedIntegerDataType.dataType;
                String code = abi[i].toLowerCase(Locale.ROOT);
                if (code.equals("b") || code.equals("j")) type = UnsignedCharDataType.dataType;
                if (code.equals("s") || code.equals("h")) type = SignedCharDataType.dataType;
                if (!abi[i].equals("u")) type = new PointerDataType(type, currentProgram.getDefaultPointerSize());
                parameters.add(new ParameterImpl("p" + i, type, currentProgram));
                JsonObject item = new JsonObject();
                item.addProperty("kind", code.equals("u") ? "uint32" : code.equals("b") ? "unsigned-char-buffer" :
                    code.equals("s") ? "signed-char-buffer" : Set.of("h","j").contains(code) ? "char-buffer" : "uint32-buffer");
                item.addProperty("read_only", abi[i].equals("c") || !abi[i].equals(code));
                if (Set.of("b","s","h","j").contains(code)) item.addProperty("element_signed", code.equals("s") || code.equals("h"));
                signature.add(item);
            }
            report.add("parameters", signature);
            target.setReturnType(UnsignedIntegerDataType.dataType, SourceType.USER_DEFINED);
            target.replaceParameters(parameters, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.USER_DEFINED);
            target.setVarArgs(false);
            decompiler.setSimplificationStyle("decompile");
            decompiler.toggleCCode(true); decompiler.toggleSyntaxTree(true);
            if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException(decompiler.getLastMessage());
            long before = System.nanoTime();
            report.addProperty("setup_seconds", (before - start) / 1e9);
            DecompileResults result = decompiler.decompileFunction(target, Integer.parseInt(args[2]), monitor);
            report.addProperty("decompile_seconds", (System.nanoTime() - before) / 1e9);
            report.addProperty("message", result.getErrorMessage());
            if (!result.decompileCompleted()) {
                report.addProperty("status", result.isTimedOut() ? "timeout" : "decompiler-error"); return;
            }
            Files.writeString(out.resolve("decompiled.c"), result.getDecompiledFunction().getC());
            JsonArray operations = new JsonArray(), blocks = new JsonArray();
            Integer entry = null;
            for (PcodeBlockBasic block : result.getHighFunction().getBasicBlocks()) {
                JsonObject descriptor = new JsonObject();
                descriptor.addProperty("id", block.getIndex());
                if (block.contains(target.getEntryPoint())) {
                    if (entry != null) throw new IllegalStateException("ambiguous entry block");
                    entry = block.getIndex();
                }
                JsonArray incoming = new JsonArray(), outgoing = new JsonArray(), ordered = new JsonArray();
                for (int i = 0; i < block.getInSize(); ++i) {
                    JsonObject edge = new JsonObject();
                    edge.addProperty("block", block.getIn(i).getIndex());
                    edge.addProperty("reverse_index", block.getInRevIndex(i)); incoming.add(edge);
                }
                for (int i = 0; i < block.getOutSize(); ++i) {
                    JsonObject edge = new JsonObject();
                    edge.addProperty("block", block.getOut(i).getIndex());
                    edge.addProperty("reverse_index", block.getOutRevIndex(i)); outgoing.add(edge);
                }
                Iterator<PcodeOp> iterator = block.getIterator();
                while (iterator.hasNext()) {
                    PcodeOp op = iterator.next();
                    JsonObject item = new JsonObject();
                    item.addProperty("opcode", op.getMnemonic());
                    item.addProperty("block", block.getIndex());
                    item.addProperty("address", op.getSeqnum().getTarget().toString());
                    if (op.getOutput() != null) item.addProperty("output", id(op.getOutput()));
                    JsonArray inputs = new JsonArray();
                    for (int i = 0; i < op.getNumInputs(); ++i) inputs.add(id(op.getInput(i)));
                    item.add("inputs", inputs);
                    ordered.add(operations.size()); operations.add(item);
                }
                descriptor.add("incoming", incoming); descriptor.add("outgoing", outgoing);
                descriptor.add("operations", ordered); blocks.add(descriptor);
            }
            if (entry == null) throw new IllegalStateException("missing entry block");
            report.addProperty("entry_block", entry);
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
                variables.add(item);
            }
            report.add("nodes", variables); report.add("operations", operations);
            report.addProperty("status", "decompiled");
        } catch (Exception error) {
            report.addProperty("status", "export-error"); report.addProperty("error", error.toString());
            throw error;
        } finally {
            decompiler.dispose();
            report.addProperty("seconds", (System.nanoTime() - start) / 1e9);
            Files.writeString(out.resolve("export.json"), new GsonBuilder().setPrettyPrinting().create().toJson(report));
        }
    }
}
