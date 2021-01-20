#!/usr/bin/env python3
#
# Copyright (C) 2021 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import List, Optional


SIMPLEPERF_DIR = Path(__file__).absolute().parent
AOSP_DIR = SIMPLEPERF_DIR.parents[2]
ART_NATIVE_METHOD_DIR = AOSP_DIR / 'art' / 'runtime' / 'native'
OUTPUT_FILE = SIMPLEPERF_DIR / 'art_jni_method_table.h'


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="generate art jni methods")
    parser.add_argument('--check-only', action='store_true',
                        help='only check if the art jni methods have changed')
    return parser.parse_args()


@dataclass
class ArtJniMethod:
    # like java.long.reflect.Method
    class_name: str
    # like invoke
    java_method_name: str
    # like Method_invoke
    native_method_name: str


class ArtJniMethodParser:
    def __init__(self):
        self.class_name_pattern = re.compile(r'REGISTER_NATIVE_METHODS\(\"(.+?)\"\)')
        # from libnativehelper/include_platform_header_only/nativehelper/jni_macros.h
        self.method_patterns = []
        self.overload_method_patterns = []
        for name in ['NATIVE_METHOD', 'FAST_NATIVE_METHOD', 'CRITICAL_NATIVE_METHOD']:
            method_s = r'\(\s*(\w+)\s*,\s*(\w+)'
            self.method_patterns.append(re.compile(r'\s+' + name + method_s))
            self.method_patterns.append(re.compile(r'\s+' + name + 'AUTOSIG' + method_s))
            overload_s = r'\(\s*(\w+)\s*,\s*(\w+)\s*,[^,]*,\s*(\w+)'
            self.overload_method_patterns.append(re.compile(r'\s+OVERLOADED_' + name + overload_s))
        self.static_function_pattern = re.compile(r'static\s+\w+\s+(\w+)\(')
        self.file_path = None

    def parse_methods(self, file_path: Path) -> List[ArtJniMethod]:
        self.file_path = file_path
        text = file_path.read_text()
        class_name = self._get_class_name(text)
        if not class_name:
            return []
        methods = self._get_methods(text, class_name)
        self._check_methods(text, methods)
        return methods

    def _get_class_name(self, text: str) -> Optional[str]:
        """ Return class name like "dalvik.system.BaseDexClassLoader". """
        m = self.class_name_pattern.search(text)
        if not m:
            return None
        class_name = m.group(1)
        assert self.class_name_pattern.search(text[m.end():]) is None
        return class_name.replace('/', '.')

    def _get_methods(self, text: str, class_name: str) -> List[ArtJniMethod]:
        class_base_name = class_name[class_name.rfind('.') + 1:]
        methods = []
        for p in self.method_patterns:
            for m in p.finditer(text):
                assert class_base_name == m.group(1)
                methods.append(
                    ArtJniMethod(
                        class_name, m.group(2),
                        class_base_name + '_' + m.group(2)))
        for p in self.overload_method_patterns:
            for m in p.finditer(text):
                assert class_base_name == m.group(1)
                methods.append(
                    ArtJniMethod(
                        class_name, m.group(2),
                        class_base_name + '_' + m.group(3)))
        return methods

    def _check_methods(self, text: str, methods: List[ArtJniMethod]):
        static_function_names = set()
        for m in self.static_function_pattern.finditer(text):
            static_function_names.add(m.group(1))
        for method in methods:
            assert method.native_method_name in static_function_names, (
                "%s isn't a static function in %s" % (method.native_method_name, self.file_path))


def collect_art_jni_methods() -> List[ArtJniMethod]:
    methods = []
    parser = ArtJniMethodParser()
    for file_path in ART_NATIVE_METHOD_DIR.iterdir():
        methods += parser.parse_methods(file_path)
    return methods


def art_jni_methods_to_str(methods: List[ArtJniMethod]):
    lines = ['// This file is generated by generate_art_jni_method_table.py.',
             '// clang-format off']
    for method in methods:
        lines.append(
            'ART_JNI_METHOD("%s", "%s")' %
            (method.class_name + '.' + method.java_method_name,
             "art::" + method.native_method_name))
    return '\n'.join(lines)


def main() -> bool:
    args = get_args()
    methods = collect_art_jni_methods()
    text = art_jni_methods_to_str(methods)
    if args.check_only:
        if text != OUTPUT_FILE.read_text():
            print('ART native methods have changed')
            return False
        return True
    OUTPUT_FILE.write_text(text)
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)