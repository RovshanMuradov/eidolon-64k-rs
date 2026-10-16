import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;

// Use as both preScript (seed) and postScript (decompile OUTPUT).
public class AnalyzeHooks extends GhidraScript {
    private final long[] entries = {
        0x401038, 0x4010e3, 0x401636, 0x40176b, 0x404cf0,
        0x404dd0, 0x405b12, 0x406019, 0x4062d0, 0x406379
    };
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args[0].equals("seed")) {
            for (long entry : entries) {
                Address a = toAddr(entry);
                disassemble(a);
                if (getFunctionAt(a) == null) createFunction(a, null);
            }
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[1])) {
            for (long entry : entries) {
                Function f = getFunctionAt(toAddr(entry));
                out.printf("\n// ENTRY %08x\n", entry);
                if (f == null) { out.println("// NO FUNCTION"); continue; }
                DecompileResults result = decompiler.decompileFunction(f, 90, monitor);
                if (result.decompileCompleted()) out.println(result.getDecompiledFunction().getC());
                else out.println("// FAILED: " + result.getErrorMessage());
            }
        } finally {
            decompiler.dispose();
        }
    }
}
