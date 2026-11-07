#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef struct Storage Storage;
typedef struct File File;
typedef enum { FSE_OK = 0, FSE_NOT_READY, FSE_EXIST, FSE_NOT_EXIST, FSE_INVALID_PARAMETER, FSE_DENIED,
               FSE_INVALID_NAME, FSE_INTERNAL, FSE_NOT_IMPLEMENTED, FSE_ALREADY_OPEN } FS_Error;
typedef enum { FSAM_READ = 1, FSAM_WRITE = 2, FSAM_READ_WRITE = 3 } FS_AccessMode;
typedef enum { FSOM_OPEN_EXISTING = 1, FSOM_OPEN_ALWAYS = 2, FSOM_OPEN_APPEND = 4, FSOM_CREATE_NEW = 8,
               FSOM_CREATE_ALWAYS = 16 } FS_OpenMode;
#define FSF_DIRECTORY 1
typedef struct { uint32_t flags; uint64_t size; } FileInfo;
static inline bool file_info_is_dir(const FileInfo* i) { return (i->flags & FSF_DIRECTORY) != 0; }

File* storage_file_alloc(Storage* s);
void storage_file_free(File* f);
bool storage_file_open(File* f, const char* path, FS_AccessMode am, FS_OpenMode om);
bool storage_file_close(File* f);
size_t storage_file_read(File* f, void* buf, size_t n);
size_t storage_file_write(File* f, const void* buf, size_t n);
FS_Error storage_common_stat(Storage* s, const char* path, FileInfo* info);
FS_Error storage_common_rename(Storage* s, const char* from, const char* to);
FS_Error storage_common_remove(Storage* s, const char* path);
FS_Error storage_common_mkdir(Storage* s, const char* path);
bool storage_simply_mkdir(Storage* s, const char* path);
bool storage_dir_open(File* f, const char* path);
bool storage_dir_read(File* f, FileInfo* info, char* name, uint16_t name_len);
bool storage_dir_close(File* f);
