all: build

test: build
	LD_LIBRARY_PATH=$$LD_LIBRARY_PATH:`pwd`/trilite python2 setup.py test

build: build-clang-plugin

clean: clean-clang-plugin

build-clang-plugin:
	$(MAKE) -C dxr/plugins/clang build

clean-clang-plugin:
	$(MAKE) -C dxr/plugins/clang clean


.PHONY: build-clang-plugin
.PHONY: clean-clang-plugin
.PHONY: all build check clean test trilite trilite-clean
