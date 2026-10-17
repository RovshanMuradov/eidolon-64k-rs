# Eidolon: build the Windows executable and run it (natively on Windows, through Wine elsewhere).
TARGET := i686-pc-windows-gnu
EXE    := target/$(TARGET)/release/eidolon-runtime.exe
RES    ?= 1920x1080
PREFIX ?= $(CURDIR)/.wine

ifeq ($(OS),Windows_NT)
  PLATFORM := Windows
else
  PLATFORM := $(shell uname -s)
endif

.PHONY: build run test clean

build:
	cargo build --release --target $(TARGET) --bin eidolon-runtime

ifeq ($(PLATFORM),Windows)
run: build
	"$(EXE)" --play
else
# A private prefix keeps the user's default Wine setup untouched; the virtual desktop keeps the window visible.
run: export WINEPREFIX := $(PREFIX)
run: export WINEDEBUG := -all
run: export WINEDLLOVERRIDES := winemenubuilder.exe,mscoree,mshtml=d
run: build
ifeq ($(PLATFORM),Darwin)
	@echo "warning: macOS OpenGL stops at 4.1 and the intro needs 4.5; it is not expected to run." >&2
endif
	wine explorer /desktop=Eidolon,$(RES) "$$(winepath -w "$(EXE)")" --play
endif

test:
	cargo test --release

clean:
	cargo clean
	rm -rf "$(PREFIX)"
