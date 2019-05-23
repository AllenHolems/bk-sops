# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云PaaS平台社区版 (BlueKing PaaS Community
Edition) available.
Copyright (C) 2017-2019 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import imp
import sys
import logging
import traceback

from contextlib import contextmanager
from abc import ABCMeta, abstractmethod

logger = logging.getLogger('root')


@contextmanager
def hook_sandbox(hook, fullname):
    hook_name = hook.__func__.func_name
    try:
        logger.info('Execute {hook_name} for {module}'.format(module=fullname, hook_name=hook_name))
        yield
    except Exception:
        logger.error('{module} {hook_name} raise exception: {traceback}'.format(
            module=fullname,
            hook_name=hook_name,
            traceback=traceback.format_exc()
        ))


class NonstandardModuleImporter(object):
    __metaclass__ = ABCMeta

    def __init__(self, modules):
        self.modules = modules

    def find_module(self, fullname, path=None):
        logger.info('=============FINDER: {cls}'.format(cls=self.__class__.__name__))
        logger.info('Try to find module: {module} in path: {path}'.format(module=fullname,
                                                                          path=path))

        logger.info('Check if in declared nonstandard modules: {modules}'.format(modules=self.modules))
        root_parent = fullname.split('.')[0]
        if root_parent not in self.modules:
            logger.info('Root module({module}) are not find in nonstandard modules'.format(module=root_parent))
            return None

        logger.info('Check if is built-in module')
        try:
            loader = imp.find_module(fullname, path)
            if loader:
                logger.info('Found {module} locally'.format(module=fullname))
                return None
        except ImportError:
            pass

        logger.info('Checking if is name repetition')
        if fullname.split('.').count(fullname.split('.')[-1]) > 1:
            logger.info('Found {module} locally'.format(module=fullname))
            return None

        with hook_sandbox(fullname=fullname, hook=self.accept_find_module_request_hook):
            self.accept_find_module_request_hook(fullname=fullname, path=path)

        return self

    def load_module(self, fullname):
        try:
            imp.acquire_lock()

            logger.info('=============LOADER: {cls}'.format(cls=self.__class__.__name__))
            logger.info('Try to load module: {module}'.format(module=fullname))

            if fullname in sys.modules:
                logger.info('Module {module} already loaded'.format(module=fullname))
                return sys.modules[fullname]

            is_pkg = self.is_package(fullname)

            try:
                src_code = self.get_source(fullname)
            except ImportError as e:
                logger.info('Get source code for {module} error: {message}'.format(module=fullname,
                                                                                   message=e.message))
                return None

            logger.info('Importing {module}'.format(module=fullname))
            mod = sys.modules.setdefault(fullname, imp.new_module(fullname))

            with hook_sandbox(fullname=fullname, hook=self.pre_load_module_hook):
                self.pre_load_module_hook(fullname=fullname, module=mod)

            mod.__file__ = self.get_file(fullname)
            mod.__loader__ = self
            mod.__name__ = fullname
            if is_pkg:
                mod.__path__ = self.get_path(fullname)
                mod.__package__ = fullname
            else:
                mod.__package__ = fullname.rpartition('.')[0]

            logger.info('Module prepared, ready to execute source code for {module}'.format(module=fullname))
            logger.info('Source code for {module}:\n{src_code}'.format(module=fullname,
                                                                       src_code=src_code))

            self._execute_src_code(src_code=src_code, module=mod)

            with hook_sandbox(fullname=fullname, hook=self.post_load_module_hook):
                self.post_load_module_hook(fullname=fullname, module=mod)

            return mod

        except Exception:

            with hook_sandbox(fullname=fullname, hook=self.import_error_hook):
                self.import_error_hook(fullname)

            err_msg = '{module} import raise exception: {traceback}'.format(
                module=fullname,
                traceback=traceback.format_exc()
            )
            logger.error(err_msg)

            if fullname in sys.modules:
                logger.info('Remove module {module} from sys.modules'.format(module=fullname))
                del sys.modules[fullname]

            raise ImportError(err_msg)

        finally:
            imp.release_lock()

    def _execute_src_code(self, src_code, module):
        exec src_code in module.__dict__

    @abstractmethod
    def is_package(self, fullname):
        raise NotImplementedError()

    @abstractmethod
    def get_code(self, fullname):
        raise NotImplementedError()

    @abstractmethod
    def get_source(self, fullname):
        raise NotImplementedError()

    @abstractmethod
    def get_file(self, fullname):
        return NotImplementedError()

    @abstractmethod
    def get_path(self, fullname):
        return NotImplementedError()

    def accept_find_module_request_hook(self, fullname, path):
        pass

    def pre_load_module_hook(self, fullname, module):
        pass

    def post_load_module_hook(self, fullname, module):
        pass

    def import_error_hook(self, fullname):
        pass