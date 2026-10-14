/* Finder entry exits after opening the authorized page; the service has its own process. */
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    char binary[PATH_MAX];
    if (!realpath(argv[0], binary)) { perror("CodeBridge launcher"); return 1; }
    char *name = strrchr(binary, '/');
    if (!name || (size_t)(name - binary) + sizeof("/CodeBridge Service") > sizeof(binary)) return 1;
    strcpy(name + 1, "CodeBridge Service");
    if (argc == 1 || (argc == 2 && strncmp(argv[1], "-psn_", 5) == 0)) {
        char *args[] = {binary, "open", NULL};
        execv(binary, args);
    } else {
        argv[0] = binary;
        execv(binary, argv);
    }
    perror("CodeBridge service entry");
    return 1;
}
