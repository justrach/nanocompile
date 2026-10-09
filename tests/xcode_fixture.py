"""Generate a deterministic C executable project for real xcodebuild tests."""
import argparse
import hashlib
from pathlib import Path


def generate(root, units=32):
    root.mkdir(parents=True, exist_ok=False)
    project = root / 'ClangFixture.xcodeproj'
    project.mkdir()
    def ident(label):
        return hashlib.sha256(label.encode()).hexdigest()[:24].upper()
    entries = []
    files = []
    builds = []
    names = ['main.c'] + [f'unit{i}.c' for i in range(units)]
    for name in names:
        f, b = ident('file:' + name), ident('build:' + name)
        files.append(f); builds.append(b)
        entries += [f'{f} = {{isa = PBXFileReference; lastKnownFileType = sourcecode.c.c; path = {name}; sourceTree = "<group>";}};',
                    f'{b} = {{isa = PBXBuildFile; fileRef = {f};}};']
    for i in range(units):
        functions = '\n'.join(f'unsigned long fn_{i}_{j}(unsigned long x) {{ return (x ^ {i * 64 + j + 1}UL) * 1664525UL + 1013904223UL; }}' for j in range(64))
        (root / f'unit{i}.c').write_text(functions + '\n')
    declarations = '\n'.join(f'extern unsigned long fn_{i}_0(unsigned long);' for i in range(units))
    checks = '\n'.join(f'if (fn_{i}_0(7) != ((7UL ^ {i * 64 + 1}UL) * 1664525UL + 1013904223UL)) return 1;' for i in range(units))
    (root / 'main.c').write_text('#include <stdio.h>\n' + declarations + '\nint main(void) {\n' + checks + '\nputs("fixture-ok"); return 0;\n}\n')
    def obj(label, body):
        entries.append(f'{ident(label)} = {{{body}}};')
    obj('product', 'isa=PBXFileReference; explicitFileType="compiled.mach-o.executable"; path=ClangFixture; sourceTree=BUILT_PRODUCTS_DIR;')
    obj('products', f'isa=PBXGroup; children=({ident("product")},); name=Products; sourceTree="<group>";')
    obj('root', 'isa=PBXGroup; children=(' + ','.join(files + [ident('products')]) + ',); sourceTree="<group>";')
    obj('sources', 'isa=PBXSourcesBuildPhase; buildActionMask=2147483647; files=(' + ','.join(builds) + ',); runOnlyForDeploymentPostprocessing=0;')
    obj('frameworks', 'isa=PBXFrameworksBuildPhase; buildActionMask=2147483647; files=(); runOnlyForDeploymentPostprocessing=0;')
    settings = 'SDKROOT=macosx; MACOSX_DEPLOYMENT_TARGET=14.0; GCC_OPTIMIZATION_LEVEL=3; CLANG_ENABLE_MODULES=NO; CODE_SIGNING_ALLOWED=NO; PRODUCT_NAME=ClangFixture;'
    for scope in ('project', 'target'):
        for config in ('Debug', 'Release'):
            obj(scope + config, f'isa=XCBuildConfiguration; buildSettings={{{settings}}}; name={config};')
        obj(scope + 'configs', f'isa=XCConfigurationList; buildConfigurations=({ident(scope + "Debug")},{ident(scope + "Release")},); defaultConfigurationIsVisible=0; defaultConfigurationName=Release;')
    obj('target', f'isa=PBXNativeTarget; buildConfigurationList={ident("targetconfigs")}; buildPhases=({ident("sources")},{ident("frameworks")},); buildRules=(); dependencies=(); name=ClangFixture; productName=ClangFixture; productReference={ident("product")}; productType="com.apple.product-type.tool";')
    obj('project', f'isa=PBXProject; attributes={{LastUpgradeCheck=2700;}}; buildConfigurationList={ident("projectconfigs")}; compatibilityVersion="Xcode 14.0"; developmentRegion=en; hasScannedForEncodings=0; knownRegions=(en,Base,); mainGroup={ident("root")}; productRefGroup={ident("products")}; projectDirPath=""; projectRoot=""; targets=({ident("target")},);')
    (project / 'project.pbxproj').write_text('// !$*UTF8*$!\n{archiveVersion=1; classes={}; objectVersion=56; objects={\n' + '\n'.join(entries) + '\n}; rootObject=' + ident('project') + ';}\n')
    return project


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    print(generate(Path(args.directory).resolve()))
