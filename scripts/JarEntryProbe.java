import java.io.InputStream;
import java.security.MessageDigest;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

/** Reports the entry selected by java.util.jar.JarFile for a duplicate name. */
public final class JarEntryProbe {
    private JarEntryProbe() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: JarEntryProbe <jar> <entry>");
        }
        try (JarFile jar = new JarFile(args[0])) {
            JarEntry entry = jar.getJarEntry(args[1]);
            if (entry == null) {
                throw new IllegalArgumentException("entry not found: " + args[1]);
            }
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = jar.getInputStream(entry)) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    digest.update(buffer, 0, count);
                }
            }
            StringBuilder sha256 = new StringBuilder();
            for (byte value : digest.digest()) {
                sha256.append(String.format("%02x", value & 0xff));
            }
            System.out.println("name=" + entry.getName());
            System.out.println("crc=" + entry.getCrc());
            System.out.println("size=" + entry.getSize());
            System.out.println("sha256=" + sha256);
        }
    }
}
