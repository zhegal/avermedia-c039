// SPDX-License-Identifier: GPL-2.0-or-later
/* Explicit maintenance utility, never invoked by capture or automated tests.
 * Only the unique present USB\\VID_07CA&PID_C039&MI_01 function is eligible.
 * Uses unmodified, catalog-verified packages already installed in Windows.
 * No package staging/removal, certificate, policy, parent or MI_00 operations. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <setupapi.h>
#include <newdev.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static int error(const char *operation) {
    fprintf(stderr,"%s failed: 0x%08lx\n",operation,GetLastError()); return 1;
}
static int verify(const wchar_t *path) {
    SP_INF_SIGNER_INFO_W info={0}; info.cbSize=sizeof(info);
    if(!SetupVerifyInfFileW(path,NULL,&info)) return error("catalog verification");
    wprintf(L"verified INF=%ls signer=%ls catalog=%ls\n",path,info.DigitalSigner,info.CatalogFile);
    return 0;
}
static int candidate(HDEVINFO set,SP_DEVINFO_DATA *device,const wchar_t *path,const wchar_t *section,SP_DRVINFO_DATA_W *out) {
    SP_DEVINSTALL_PARAMS_W params={0}; params.cbSize=sizeof(params);
    if(!SetupDiGetDeviceInstallParamsW(set,device,&params)) return error("get install params");
    params.Flags|=DI_ENUMSINGLEINF;
    params.FlagsEx|=DI_FLAGSEX_ALLOWEXCLUDEDDRVS;
    if(wcslen(path)>=MAX_PATH) return 1;
    wcscpy(params.DriverPath,path);
    if(!SetupDiSetDeviceInstallParamsW(set,device,&params) ||
       !SetupDiBuildDriverInfoList(set,device,SPDIT_CLASSDRIVER)) return error("build installed class list");
    for(DWORD n=0;;n++) {
        SP_DRVINFO_DATA_W driver={0}; driver.cbSize=sizeof(driver);
        if(!SetupDiEnumDriverInfoW(set,device,SPDIT_CLASSDRIVER,n,&driver)) break;
        DWORD size=0;
        SetupDiGetDriverInfoDetailW(set,device,&driver,NULL,0,&size);
        SP_DRVINFO_DETAIL_DATA_W *detail=calloc(1,size);
        if(!detail) return 1;
        detail->cbSize=sizeof(*detail);
        BOOL ok=SetupDiGetDriverInfoDetailW(set,device,&driver,detail,size,NULL);
        if(ok) wprintf(L"candidate description=%ls section=%ls INF=%ls hardware=%ls\n",
                       driver.Description,detail->SectionName,detail->InfFileName,detail->HardwareID);
        const wchar_t *hardware=!_wcsicmp(section,L"WINUSB")?L"usb\\ms_comp_winusb":L"USB\\VID_07CA&PID_C039&MI_01";
        int match=ok && !_wcsicmp(detail->SectionName,section) && !_wcsicmp(detail->HardwareID,hardware);
        free(detail);
        if(match) { *out=driver; return 0; }
    }
    fprintf(stderr,"Required installed driver section not found; no installation attempted\n");
    return 1;
}
typedef BOOL (WINAPI *install_device)(HWND,HDEVINFO,PSP_DEVINFO_DATA,PSP_DRVINFO_DATA_W,DWORD,PBOOL);
static int interface_guid(HDEVINFO set,SP_DEVINFO_DATA *target,int enable) {
    /* Normal WinUSB discovery configuration, not a security/driver-store key.
     * Never replace another interface registration. Baseline has no such value. */
    static const wchar_t guid[]=L"{DC5D64D5-1DDB-4B6F-80CB-3472927954AE}\0";
    /* DIREG_DEV already opens Device Parameters, not the Enum instance root. */
    HKEY parameters=SetupDiOpenDevRegKey(set,target,DICS_FLAG_GLOBAL,0,DIREG_DEV,KEY_READ|KEY_WRITE);
    if(parameters==INVALID_HANDLE_VALUE) return error("MI_01 Device Parameters");
    wchar_t previous[256]={0}; DWORD bytes=sizeof(previous),type=0;
    LONG code=RegQueryValueExW(parameters,L"DeviceInterfaceGUIDs",NULL,&type,(BYTE *)previous,&bytes);
    if(code!=ERROR_FILE_NOT_FOUND && (code || type!=REG_MULTI_SZ || bytes!=sizeof(guid) || memcmp(previous,guid,sizeof(guid)))) {
        RegCloseKey(parameters);
        if(!enable) return 0; /* Preserve any registration owned by AVerPola. */
        fputs("Unrecognized DeviceInterfaceGUIDs; refusing overwrite\n",stderr); return 1;
    }
    if(enable) code=RegSetValueExW(parameters,L"DeviceInterfaceGUIDs",0,REG_MULTI_SZ,(const BYTE *)guid,sizeof(guid));
    else if(code==ERROR_SUCCESS) code=RegDeleteValueW(parameters,L"DeviceInterfaceGUIDs");
    else code=ERROR_SUCCESS;
    RegCloseKey(parameters);
    if(code) { SetLastError(code); return error("configure MI_01 interface GUID"); }
    printf("MI_01 application interface GUID %s\n",enable?"registered":"absent/restored");
    return 0;
}
static int apply(HDEVINFO set,SP_DEVINFO_DATA *target,const wchar_t *path,
                 const wchar_t *section,const wchar_t *class_id,install_device install) {
    SetupDiDestroyDriverInfoList(set,target,SPDIT_CLASSDRIVER);
    wchar_t previous_class[64]={0}; DWORD type=0;
    if(!SetupDiGetDeviceRegistryPropertyW(set,target,SPDRP_CLASSGUID,&type,
            (BYTE *)previous_class,sizeof(previous_class),NULL)) return error("read MI_01 setup class");
    if(_wcsicmp(previous_class,class_id) && !SetupDiSetDeviceRegistryPropertyW(set,target,SPDRP_CLASSGUID,
            (const BYTE *)class_id,(DWORD)((wcslen(class_id)+1)*sizeof(wchar_t)))) return error("set MI_01 setup class");
    SP_DRVINFO_DATA_W selected={0};
    if(candidate(set,target,path,section,&selected)) return 1;
    BOOL reboot=FALSE;
    if(!install(NULL,set,target,&selected,0,&reboot)) return error("DiInstallDevice");
    printf("DiInstallDevice succeeded; reboot_required=%d\n",reboot);
    /* Device installation can recreate Device Parameters; register afterwards. */
    if(interface_guid(set,target,!_wcsicmp(section,L"WINUSB"))) return 1;
    if(!reboot) {
        /* Same-driver reinstallation may not restart WinUSB, which reads the
         * application GUID at start. Request a restart of this function only. */
        SP_PROPCHANGE_PARAMS change={0};
        change.ClassInstallHeader.cbSize=sizeof(change.ClassInstallHeader);
        change.ClassInstallHeader.InstallFunction=DIF_PROPERTYCHANGE;
        change.StateChange=DICS_PROPCHANGE;
        change.Scope=DICS_FLAG_CONFIGSPECIFIC;
        if(!SetupDiSetClassInstallParamsW(set,target,&change.ClassInstallHeader,sizeof(change)) ||
           !SetupDiCallClassInstaller(DIF_PROPERTYCHANGE,set,target)) return error("restart MI_01 function");
        puts("MI_01 function restarted");
    }
    return reboot?2:0;
}
int main(int argc,char **argv) {
    int bind=argc==2 && !strcmp(argv[1],"--bind-winusb");
    int restore=argc==2 && !strcmp(argv[1],"--restore-avermedia");
    int plan=argc==2 && !strcmp(argv[1],"--plan");
    if(!bind && !restore && !plan) {
        fputs("Usage: c039-driver --plan | --bind-winusb | --restore-avermedia\n",stderr); return 64;
    }
    if(!plan) {
        wchar_t logfile[MAX_PATH];
        DWORD length=GetModuleFileNameW(NULL,logfile,MAX_PATH);
        wchar_t *slash=length && length<MAX_PATH?wcsrchr(logfile,L'\\'):NULL;
        if(!slash || (size_t)(slash-logfile)+20>=MAX_PATH) return 1;
        wcscpy(slash+1,restore?L"driver-restore.log":L"driver-bind.log");
        FILE *log=_wfreopen(logfile,L"a",stdout);
        if(!log || !_wfreopen(logfile,L"a",stderr)) return 1;
        puts("\nC039 explicit per-device driver operation");
    }
    setvbuf(stdout,NULL,_IONBF,0);
    wchar_t root[MAX_PATH],winusb[MAX_PATH],vendor[MAX_PATH];
    if(!GetWindowsDirectoryW(root,MAX_PATH)) return error("Windows directory");
    if(swprintf(winusb,MAX_PATH,L"%ls\\INF\\winusb.inf",root)<0 ||
       swprintf(vendor,MAX_PATH,L"%ls\\INF\\oem13.inf",root)<0) return 1;
    /* This experiment's rollback package is pinned to the recorded machine.
     * Fail closed if it has changed; do not guess another OEM package. */
    if(verify(winusb) || verify(vendor)) return 1;
    HDEVINFO set=SetupDiGetClassDevsW(NULL,L"USB",NULL,DIGCF_ALLCLASSES|DIGCF_PRESENT);
    if(set==INVALID_HANDLE_VALUE) return error("enumerate USB devices");
    SP_DEVINFO_DATA target={0}; unsigned count=0;
    for(DWORD n=0;;n++) {
        SP_DEVINFO_DATA device={0}; device.cbSize=sizeof(device);
        if(!SetupDiEnumDeviceInfo(set,n,&device)) break;
        wchar_t id[512];
        if(!SetupDiGetDeviceInstanceIdW(set,&device,id,512,NULL)) continue;
        const wchar_t *prefix=L"USB\\VID_07CA&PID_C039&MI_01\\";
        if(!_wcsnicmp(id,prefix,wcslen(prefix))) { target=device; count++; wprintf(L"target=%ls\n",id); }
    }
    if(count!=1) { fprintf(stderr,"Expected exactly one MI_01, found %u\n",count); SetupDiDestroyDeviceInfoList(set); return 1; }
    wchar_t service[256]={0}; DWORD type=0;
    if(!SetupDiGetDeviceRegistryPropertyW(set,&target,SPDRP_SERVICE,&type,(BYTE *)service,sizeof(service),NULL)) {
        SetupDiDestroyDeviceInfoList(set); return error("read target service");
    }
    wprintf(L"current service=%ls\n",service);
    if(_wcsicmp(service,L"AVerPola") && _wcsicmp(service,L"WinUSB")) {
        fputs("Unexpected current service; refusing change\n",stderr); SetupDiDestroyDeviceInfoList(set); return 1;
    }
    HDEVINFO drivers=SetupDiCreateDeviceInfoList(NULL,NULL);
    if(drivers==INVALID_HANDLE_VALUE) { SetupDiDestroyDeviceInfoList(set); return error("driver list"); }
    SP_DRVINFO_DATA_W selected={0};
    SP_DRVINFO_DATA_W rollback={0};
    int failed=candidate(drivers,NULL,vendor,L"AVerCapturex64_Vista_C039",&rollback);
    SetupDiDestroyDriverInfoList(drivers,NULL,SPDIT_CLASSDRIVER);
    const wchar_t *path=restore?vendor:winusb;
    const wchar_t *section=restore?L"AVerCapturex64_Vista_C039":L"WINUSB";
    if(!failed) failed=candidate(drivers,NULL,path,section,&selected);
    if(!failed && plan) puts("PLAN ONLY: class transition Media <-> USBDevice on MI_01; no install or registry changes");
    if(!failed && !plan) {
        HMODULE module=LoadLibraryExW(L"newdev.dll",NULL,LOAD_LIBRARY_SEARCH_SYSTEM32);
        install_device install=module?(install_device)(void *)GetProcAddress(module,"DiInstallDevice"):NULL;
        const wchar_t *media=L"{4d36e96c-e325-11ce-bfc1-08002be10318}";
        const wchar_t *usb=L"{88bae032-5a81-49f0-bc3d-a4ff138216d6}";
        if(!install) failed=error("load system DiInstallDevice");
        else {
            failed=apply(set,&target,path,section,restore?media:usb,install);
            if(failed==1) {
                puts("Installation failed: attempting original binding rollback on MI_01 only");
                int was_vendor=!_wcsicmp(service,L"AVerPola");
                int rollback_result=apply(set,&target,was_vendor?vendor:winusb,
                        was_vendor?L"AVerCapturex64_Vista_C039":L"WINUSB",was_vendor?media:usb,install);
                printf("rollback_result=%d\n",rollback_result);
            }
        }
        if(module) FreeLibrary(module);
    }
    SetupDiDestroyDeviceInfoList(drivers);
    SetupDiDestroyDeviceInfoList(set);
    return failed;
}
