# Eidolon: build, run and verify against the original (natively on Windows, through Wine elsewhere).
TARGET := i686-pc-windows-gnu
EXE    := target/$(TARGET)/release/eidolon-runtime.exe
RES    ?= 1920x1080
PREFIX ?= $(CURDIR)/.wine
# Expected hashes: a reference captured on this machine (make reference) wins over the shipped one.
REF    := $(if $(wildcard verify/local/frames.sha256),verify/local,verify)
FRAMES := .build/rust-frames.sha256

ifeq ($(OS),Windows_NT)
  PLATFORM := Windows
  ENGINE   := cargo run --release --target $(TARGET) --bin eidolon-engine --
else
  PLATFORM := $(shell uname -s)
  ENGINE   := cargo run --release --bin eidolon-engine --
endif

.PHONY: build run verify verify-audio reference size run-size check-size-inputs test-size test clean

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

# Byte-exact PCM check on the CPU; no GPU or Wine needed.
verify-audio:
	@echo "Synthesizing the full soundtrack (a few minutes)..."
	@actual=$$($(ENGINE) --pcm-sha256) && expected=$$(cat $(REF)/pcm.sha256) && \
	if [ "$$actual" = "$$expected" ]; then echo "PASS audio: $$actual"; \
	else echo "FAIL audio: got $$actual, expected $$expected ($(REF)/pcm.sha256)"; exit 1; fi

# Byte-exact check of all 27 000 frames rendered with a controlled clock.
verify: build
	@mkdir -p .build && rm -f $(FRAMES)
	@echo "Rendering 27000 frames with a controlled clock (about 20-30 minutes); expected hashes: $(REF)/frames.sha256"
ifeq ($(PLATFORM),Windows)
	"$(EXE)" --capture $(FRAMES)
else
	python3 tools/reference/headless.py --prefix .build/rust-prefix $(EXE) --capture 'Z:$(subst /,\,$(CURDIR)/$(FRAMES))'
endif
	@if cmp -s $(FRAMES) $(REF)/frames.sha256; then echo "PASS frames: 27000/27000 identical to $(REF)/frames.sha256"; \
	else echo "FAIL frames: first differences (frame, hash):"; diff $(REF)/frames.sha256 $(FRAMES) | head -6; exit 1; fi

# Capture the original EXE on this machine's GPU into verify/local (Linux only).
# ARCHIVE=path/to/eidolon_..._rc4.zip uses a downloaded archive; otherwise it is downloaded.
reference:
ifeq ($(PLATFORM),Linux)
	python3 tools/reference/capture_original.py $(if $(ARCHIVE),--archive "$(ARCHIVE)")
else
	@echo "make reference runs the original under Wine with capture proxies and needs Linux." >&2; exit 1
endif

# Size-optimized build (no_std Rust + patched kkrunchy), compared with size/expected.sha256 (Linux only).
size:
ifeq ($(PLATFORM),Linux)
	$(MAKE) check-size-inputs
	python3 size/build.py
else
	@echo "make size packs with kkrunchy under Wine and needs Linux." >&2; exit 1
endif

check-size-inputs:
	python3 size/tools/generate_audio.py --check
	python3 size/tools/reconstruct_shaders.py --check
	python3 size/packer/generate_model.py --check
	python3 size/crate/tools/rust/layout.py --check

# CPU-only regression checks for the size-build transformations (requires glslangValidator).
test-size: check-size-inputs
	python3 -m unittest discover -s size/tests -v
	python3 -m unittest discover -s tests -p test_size_layout.py -v
	python3 -m unittest discover -s size/tools -p test_shader_validation.py -v

# Like the original, the size-optimized build reads gm.dls from the Windows system directory.
run-size: export WINEPREFIX := $(PREFIX)
run-size: export WINEDEBUG := -all
run-size: export WINEDLLOVERRIDES := winemenubuilder.exe,mscoree,mshtml=d
run-size: size
	python3 tools/reference/install_bank.py "$(PREFIX)"
	wine explorer /desktop=Eidolon,$(RES) "$$(winepath -w .build/eidolon-size.exe)"

test:
	cargo test --release

clean:
	cargo clean
	rm -rf "$(PREFIX)" .build
