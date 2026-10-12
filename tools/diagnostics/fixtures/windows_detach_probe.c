/* Synthetic Windows loader test. Build with MSVC /LD and kernel32.lib.
 * Set AIPACS_EXIT_DETACH_MARKER only in a disposable Python subprocess.
 * No Qt, workstation, patient data or application runtime is loaded.
 */
__declspec(dllimport) unsigned long __stdcall GetEnvironmentVariableW(const unsigned short*, unsigned short*, unsigned long);
__declspec(dllimport) void* __stdcall CreateFileW(const unsigned short*, unsigned long, unsigned long, void*, unsigned long, unsigned long, void*);
__declspec(dllimport) int __stdcall WriteFile(void*, const void*, unsigned long, unsigned long*, void*);
__declspec(dllimport) int __stdcall CloseHandle(void*);

int __stdcall DllMain(void* module, unsigned long reason, void* reserved) {
    if (reason == 0 && reserved) {
        unsigned short path[2048];
        unsigned long written = 0;
        if (GetEnvironmentVariableW(L"AIPACS_EXIT_DETACH_MARKER", path, 2048)) {
            void* file = CreateFileW(path, 0x40000000, 0, 0, 2, 0x80, 0);
            if (file != (void*)-1) {
                WriteFile(file, "DETACH", 6, &written, 0);
                CloseHandle(file);
            }
        }
    }
    return 1;
}
