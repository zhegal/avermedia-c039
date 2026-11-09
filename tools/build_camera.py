#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the native C039 camera app/extension; never install or change security."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--team', help='Apple Developer team ID; enables automatic development signing')
    parser.add_argument('--provision', action='store_true', help='allow Xcode to request provisioning profiles')
    args = parser.parse_args()
    if args.team and not re.fullmatch(r'[A-Z0-9]{10}', args.team):
        parser.error('team must be a 10-character Apple team ID')
    if args.provision and not args.team:
        parser.error('--provision requires --team')
    folder = ROOT / 'build/camera-project'
    project = folder / 'C039.xcodeproj'
    project.mkdir(parents=True, exist_ok=True)
    group = '$(TeamIdentifierPrefix)io.github.zhegal.C039.Camera'
    for name, extension in [('Host', False), ('Camera', True)]:
        info = dict(CFBundleDevelopmentRegion='en', CFBundleExecutable='$(EXECUTABLE_NAME)',
            CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)', CFBundleInfoDictionaryVersion='6.0',
            CFBundleName='AVerMedia C039', CFBundlePackageType='SYSX' if extension else 'APPL',
            CFBundleShortVersionString='0.2.0', CFBundleVersion='1', LSMinimumSystemVersion='12.3',
            NSSystemExtensionUsageDescription='Capture Composite video from AVerMedia C039 as a system camera.')
        if extension:
            info['CMIOExtension'] = dict(CMIOExtensionMachServiceName='$(TeamIdentifierPrefix)$(PRODUCT_BUNDLE_IDENTIFIER)')
        else:
            info.update(NSPrincipalClass='NSApplication', LSApplicationCategoryType='public.app-category.utilities')
        entitlements = {'com.apple.security.app-sandbox': True, 'com.apple.security.application-groups': [group]}
        entitlements['com.apple.security.device.usb' if extension else 'com.apple.developer.system-extension.install'] = True
        for suffix, value in [('plist', info), ('entitlements', entitlements)]:
            (folder / f'{name}.{suffix}').write_bytes(plistlib.dumps(value))
    objects = {}

    def obj(label, isa, **values):
        key = hashlib.sha256(label.encode()).hexdigest()[:24].upper()
        objects[key] = dict(isa=isa, **values)
        return key

    def config(label, settings):
        entry = obj(label + '.debug', 'XCBuildConfiguration', name='Debug', buildSettings=settings)
        return obj(label + '.configs', 'XCConfigurationList', buildConfigurations=[entry],
                   defaultConfigurationIsVisible='0', defaultConfigurationName='Debug')

    common = dict(SDKROOT='macosx', MACOSX_DEPLOYMENT_TARGET='12.3', SWIFT_VERSION='5.0',
        CLANG_ENABLE_MODULES='YES', CLANG_ENABLE_OBJC_ARC='YES', GCC_C_LANGUAGE_STANDARD='c11',
        HEADER_SEARCH_PATHS=str(ROOT / 'src'), GCC_WARN_ABOUT_DEPRECATED_FUNCTIONS='NO',
        CODE_SIGN_STYLE='Automatic', DEVELOPMENT_TEAM=args.team or '',
        CODE_SIGN_IDENTITY='Apple Development', ENABLE_HARDENED_RUNTIME='YES',
        ENABLE_APP_SANDBOX='YES', GENERATE_INFOPLIST_FILE='NO',
        CONFIGURATION_BUILD_DIR=str(ROOT / 'build/camera-products'),
        SWIFT_OPTIMIZATION_LEVEL='-O', GCC_OPTIMIZATION_LEVEL='2', ARCHS='arm64')
    refs = []

    def source(path, language):
        ref = obj('file.' + path, 'PBXFileReference', path=str(ROOT / path), sourceTree='<absolute>', lastKnownFileType=language)
        refs.append(ref)
        return obj('build.' + path, 'PBXBuildFile', fileRef=ref)

    host_sources = [source('camera/Host.swift', 'sourcecode.swift')]
    camera_sources = [source('camera/Extension.swift', 'sourcecode.swift')]
    camera_sources += [source('src/' + name + '.c', 'sourcecode.c.c') for name in
                       ('capture_device', 'iso_probe', 'av_init', 'video_standard', 'frame_decoder')]
    products = []
    targets = []
    camera_id = None
    camera_product = None
    for name, extension, files in [('Camera', True, camera_sources), ('Host', False, host_sources)]:
        product_name = 'io.github.zhegal.C039.Camera.systemextension' if extension else 'C039 Camera.app'
        product = obj(name + '.product', 'PBXFileReference', path=product_name, sourceTree='BUILT_PRODUCTS_DIR',
                      explicitFileType='wrapper.system-extension' if extension else 'wrapper.application')
        products.append(product)
        phases = [obj(name + '.sources', 'PBXSourcesBuildPhase', buildActionMask='2147483647', files=files,
                      runOnlyForDeploymentPostprocessing='0')]
        dependencies = []
        if not extension:
            embedded = obj('embed.camera', 'PBXBuildFile', fileRef=camera_product,
                           settings={'ATTRIBUTES': ['CodeSignOnCopy']})
            phases.append(obj('embed.phase', 'PBXCopyFilesBuildPhase', buildActionMask='2147483647',
                dstPath='$(CONTENTS_FOLDER_PATH)/Library/SystemExtensions', dstSubfolderSpec='16',
                files=[embedded], runOnlyForDeploymentPostprocessing='0'))
            dependencies.append(obj('host.dependency', 'PBXTargetDependency', target=camera_id))
        settings = dict(common, PRODUCT_NAME='io.github.zhegal.C039.Camera' if extension else 'C039 Camera',
            PRODUCT_BUNDLE_IDENTIFIER='io.github.zhegal.C039.Camera' if extension else 'io.github.zhegal.C039',
            INFOPLIST_FILE=str(folder / f'{name}.plist'), CODE_SIGN_ENTITLEMENTS=str(folder / f'{name}.entitlements'),
            OTHER_LDFLAGS=['-framework', 'IOKit', '-framework', 'CoreFoundation', '-framework', 'CoreMediaIO',
                            '-framework', 'CoreMedia', '-framework', 'CoreVideo'] if extension else
                           ['-framework', 'AppKit', '-framework', 'SystemExtensions'])
        if extension:
            settings.update(SWIFT_OBJC_BRIDGING_HEADER=str(ROOT / 'camera/Bridge.h'), SKIP_INSTALL='YES')
        target = obj(name + '.target', 'PBXNativeTarget', name=name, productName=settings['PRODUCT_NAME'],
            productReference=product, productType='com.apple.product-type.system-extension' if extension else
            'com.apple.product-type.application', buildConfigurationList=config(name, settings),
            buildPhases=phases, buildRules=[], dependencies=dependencies)
        targets.append(target)
        if extension:
            camera_id, camera_product = target, product
    product_group = obj('products', 'PBXGroup', name='Products', sourceTree='<group>', children=products)
    root_group = obj('root.group', 'PBXGroup', sourceTree='<group>', children=refs + [product_group])
    root = obj('root.project', 'PBXProject', mainGroup=root_group, productRefGroup=product_group,
        buildConfigurationList=config('Project', {}), compatibilityVersion='Xcode 14.0',
        developmentRegion='en', knownRegions=['en'], projectDirPath='', projectRoot='', targets=targets,
        attributes={'LastUpgradeCheck': '1600'})
    (project / 'project.pbxproj').write_bytes(plistlib.dumps(dict(archiveVersion='1', objectVersion='56',
        classes={}, objects=objects, rootObject=root)))
    command = ['xcodebuild', '-project', str(project), '-target', 'Host', '-configuration', 'Debug', 'build',
               'SYMROOT=' + str(ROOT / 'build/camera-objects')]
    if args.provision:
        command.append('-allowProvisioningUpdates')
    if not args.team:
        command.append('CODE_SIGNING_ALLOWED=NO')
    return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
