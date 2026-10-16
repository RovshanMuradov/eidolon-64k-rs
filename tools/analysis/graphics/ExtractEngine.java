import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;

// Isolated raw-image analysis; never operates on the capture/Ghidra projects.
public class ExtractEngine extends GhidraScript {
    private final long[] entries = {0x406019, 0x4062d0, 0x406379};
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
        } finally { decompiler.dispose(); }
    }
}
