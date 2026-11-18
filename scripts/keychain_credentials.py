"""Project-only credentials in the macOS login Keychain; never print values."""
import ctypes


def _api():
    lib=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    pointer=ctypes.c_void_p;uint=ctypes.c_uint32;char=ctypes.c_char_p
    lib.SecKeychainFindGenericPassword.argtypes=[pointer,uint,char,uint,char,ctypes.POINTER(uint),ctypes.POINTER(pointer),ctypes.POINTER(pointer)]
    lib.SecKeychainAddGenericPassword.argtypes=[pointer,uint,char,uint,char,uint,pointer,ctypes.POINTER(pointer)]
    lib.SecKeychainItemModifyAttributesAndData.argtypes=[pointer,pointer,uint,pointer]
    lib.SecKeychainItemFreeContent.argtypes=[pointer,pointer]
    lib.SecKeychainItemDelete.argtypes=[pointer]
    for name in ['SecKeychainFindGenericPassword','SecKeychainAddGenericPassword','SecKeychainItemModifyAttributesAndData','SecKeychainItemFreeContent','SecKeychainItemDelete']:
        getattr(lib,name).restype=ctypes.c_int32
    cf=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFRelease.argtypes=[pointer];cf.CFRelease.restype=None
    return lib,cf


def credential(name,value=None):
    lib,cf=_api();service=('BELLACROSS daily '+name).encode();account=b'thebellacross'
    length=ctypes.c_uint32();data=ctypes.c_void_p();item=ctypes.c_void_p()
    result=lib.SecKeychainFindGenericPassword(None,len(service),service,len(account),account,ctypes.byref(length),ctypes.byref(data),ctypes.byref(item))
    if result not in (0,-25300):
        raise RuntimeError(f'The macOS login Keychain is unavailable (status {result}).')
    try:
        existing=ctypes.string_at(data,length.value).decode() if result==0 else None
        if value is None:return existing
        raw=value.encode();buffer=ctypes.create_string_buffer(raw)
        if result==0:written=lib.SecKeychainItemModifyAttributesAndData(item,None,len(raw),ctypes.cast(buffer,ctypes.c_void_p))
        else:written=lib.SecKeychainAddGenericPassword(None,len(service),service,len(account),account,len(raw),ctypes.cast(buffer,ctypes.c_void_p),None)
        if written!=0:raise RuntimeError(f'Could not save the project credential in Keychain (status {written}).')
        return value
    finally:
        if data:lib.SecKeychainItemFreeContent(None,data)
        if item:cf.CFRelease(item)


def self_test():
    """Creates and removes one disposable non-secret test entry, never user data."""
    import uuid
    name='storage test '+str(uuid.uuid4());value='non-secret-storage-test'
    credential(name,value)
    assert credential(name)==value
    lib,cf=_api();service=('BELLACROSS daily '+name).encode();account=b'thebellacross';item=ctypes.c_void_p()
    result=lib.SecKeychainFindGenericPassword(None,len(service),service,len(account),account,None,None,ctypes.byref(item))
    if result!=0:raise RuntimeError('Could not locate the disposable Keychain test entry.')
    try:
        if lib.SecKeychainItemDelete(item)!=0:raise RuntimeError('Could not remove the disposable Keychain test entry.')
    finally:cf.CFRelease(item)
    print('PASS: project-only Keychain write/read; disposable test entry removed.')


if __name__=='__main__':self_test()
