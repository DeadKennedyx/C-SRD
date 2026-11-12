// Export ordered effects and CFG for the supplied public private-region ABI.
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

public class ExportCSRDRegions extends HeadlessScript {
    private final IdentityHashMap<Varnode, Integer> ids = new IdentityHashMap<>();
    private final List<Varnode> nodes = new ArrayList<>();
    private int id(Varnode node) {
        if (!ids.containsKey(node)) { ids.put(node, nodes.size()); nodes.add(node); }
        return ids.get(node);
    }
    private void configureCallback(Function f) throws Exception {
        String name = f.getName();
        if (!name.equals("next_value") && !name.equals("record_event")) return;
        f.setReturnType(name.equals("next_value") ? UnsignedIntegerDataType.dataType : VoidDataType.dataType, SourceType.USER_DEFINED);
        List<Variable> params = new ArrayList<>();
        params.add(new ParameterImpl("value", UnsignedIntegerDataType.dataType, currentProgram));
        f.replaceParameters(params, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.USER_DEFINED);
        f.setVarArgs(false);
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 4) throw new IllegalArgumentException("function p,u,s-ABI timeout-seconds output-directory");
        Path out = Paths.get(args[3]);
        JsonObject report = new JsonObject();
        report.addProperty("schema_version", 6);
        report.addProperty("boolean_constants", "high-type-nonzero-is-true");
        report.addProperty("memory_model", "ordered-u32-regions-v1");
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
                if (!Set.of("u", "p", "s").contains(abi[i])) throw new IllegalArgumentException("unknown ABI type");
                DataType type = UnsignedIntegerDataType.dataType;
                if (abi[i].equals("p")) type = new PointerDataType(type, currentProgram.getDefaultPointerSize());
                if (abi[i].equals("s")) type = IntegerDataType.dataType;
                parameters.add(new ParameterImpl("p" + i, type, currentProgram));
                JsonObject item = new JsonObject();
                item.addProperty("kind", abi[i].equals("p") ? "uint32-buffer" : abi[i].equals("s") ? "int32" : "uint32");
                item.addProperty("read_only", false);
                signature.add(item);
            }
            report.add("parameters", signature);
            report.addProperty("return_type", args[0].equals("region_outputs") ? "int32" : "uint32");
            target.setReturnType(args[0].equals("region_outputs") ? IntegerDataType.dataType : UnsignedIntegerDataType.dataType, SourceType.USER_DEFINED);
            target.replaceParameters(parameters, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.USER_DEFINED);
            target.setVarArgs(false);
            // Known public callbacks; no implementation/source supplied to this exporter.
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) configureCallback(f);
            for (Function f : currentProgram.getFunctionManager().getExternalFunctions()) configureCallback(f);
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
                    JsonObject edge = new JsonObject(); edge.addProperty("block", block.getIn(i).getIndex());
                    edge.addProperty("reverse_index", block.getInRevIndex(i)); incoming.add(edge);
                }
                for (int i = 0; i < block.getOutSize(); ++i) {
                    JsonObject edge = new JsonObject(); edge.addProperty("block", block.getOut(i).getIndex());
                    edge.addProperty("reverse_index", block.getOutRevIndex(i)); outgoing.add(edge);
                }
                Iterator<PcodeOp> iterator = block.getIterator();
                while (iterator.hasNext()) {
                    PcodeOp op = iterator.next();
                    JsonObject item = new JsonObject();
                    item.addProperty("opcode", op.getMnemonic());
                    item.addProperty("block", block.getIndex());
                    item.addProperty("address", op.getSeqnum().getTarget().toString());
                    if (op.getOpcode() == PcodeOp.CALL) {
                        Function callee = currentProgram.getFunctionManager().getFunctionAt(op.getInput(0).getAddress());
                        if (callee != null) {
                            if (callee.isThunk()) callee = callee.getThunkedFunction(true);
                            item.addProperty("callee", callee.getName());
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
            if (entry == null) throw new IllegalStateException("missing entry block");
            report.addProperty("entry_block", entry);
            report.addProperty("operation_order", "basic-block-live-order");
            report.add("blocks", blocks);
            JsonArray variables = new JsonArray();
            for (Varnode node : nodes) {
                JsonObject item = new JsonObject();
                item.addProperty("size", node.getSize());
                item.addProperty("input", node.isInput());
                if (node instanceof VarnodeAST && ((VarnodeAST)node).getHigh() != null) {
                    DataType type = ((VarnodeAST)node).getHigh().getDataType();
                    item.addProperty("boolean_type", type instanceof BooleanDataType);
                }
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
