/**
 * @file history.cpp
 * @author Sean McGinty (newfolderlocation@gmail.com)
 * @brief Displays the history of commands.
 * @version 1.0
 * @date 2022-06-15
 */

#include "../internal.hpp"
#include <sdk/os/file.h>

// write to history file with int argc, char **argv 
extern int history_main(int argc, char **argv) {
    terminal->ClearBuffer();
    char outBuf[BUF_SIZE];

    // check if history file exists
    int findHandle;
    wchar_t fileName[100];
    struct File_FindInfo findInfoBuf;
    int ret = File_FindFirst(g_whistory, &findHandle, fileName, &findInfoBuf);
    if (ret < 0) {
        // history file does not exist
        // create the file
        int fd = File_Open(g_history, FILE_OPEN_WRITE | FILE_OPEN_CREATE);
        if (fd < 0) {
            // failed to create file
            strcpy(outBuf, "Failed to create history file.\n");
            terminal->WriteChars(outBuf);
            File_FindClose(findHandle);
            File_Close(fd);
            return -1;
        }
        // close the file
        File_Close(fd);

        // as history file will be empty, return
        return 0;

    // history file exists, check if it is a directory
    } else if (findInfoBuf.type == File_EntryTypeDirectory) {
        // history file is a directory
        strcpy(outBuf, "History file is a directory.\n");
        terminal->WriteChars(outBuf);
        File_FindClose(findHandle);
        return -1;
    }

    File_FindClose(findHandle);

    // just cat the file for now
    char *argv2[3];
    argv2[0] = "cat";
    argv2[1] = g_history;
    argv2[2] = 0;
    cat_main(2, argv2);
    
    return 0; // return 0 on success
}
