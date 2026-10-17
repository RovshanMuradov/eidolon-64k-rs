/* Default i686-w64-mingw32 ld script (binutils) with a function and data order chosen
   by hill-climbing the kkrunchy packed size; see size/README.md. */
SECTIONS
{
  /* Make the virtual address and file offset synced if the alignment is
     lower than the target page size. */
  . = SIZEOF_HEADERS;
  . = ALIGN(__section_alignment__);
  .text  __image_base__ + ( __section_alignment__ < 0x1000 ? . : __section_alignment__ ) :
  {
    KEEP (*(SORT_NONE(.init)))
    *(.text)
    *(.text$_RNvMNtCs*_7eidolon7runtimeNtB*_6Window4pump)
    *(.text$_RNvNtCs*_7eidolon16compact_graphics4uint)
    *(.text$_RNvMs2_NtCs*_5alloc7raw_vecNtB*_11RawVecInner10deallocateB*_)
    *(.text$_RINvNtCs*_4core3ptr9drop_glueINtNtCs*_5alloc5boxed3BoxNtNtNtCs*_7eidolon5audio7runtime7RuntimeEEB*_)
    *(.text$_RINvNtCs*_4core3mem4dropINtNtCs*_5alloc5boxed3BoxNtNtNtCs*_7eidolon9synthesis14minimal_worker3JobEEB*_)
    *(.text$_RNvNtNtCs*_7eidolon5audio7runtime7release)
    *(.text$_RNvMNtCs*_7eidolon8graphicsNtB*_8Graphics7compile)
    *(.text$_RNCNvNtCs*_7eidolon7runtime3runs_0B*_)
    *(.text$_RINvNtCs*_4core3ptr9drop_glueINtNtB*_6option6OptionINtNtB*_6result6ResultINtNtCs*_5alloc3vec3VecfENtCs*_7eidolon12RuntimeErrorEEEB1U_)
    *(.text$_RNvNtCs*_7eidolon7runtime11window_proc)
    *(.text$_RNvNtCs*_7eidolon7minimal13message_bytes)
    *(.text$eidolon_read_gm_dls)
    *(.text$_RNvXs_NtCs*_7eidolon7minimalNtB*_4HeapNtNtNtCs*_4core5alloc6global11GlobalAlloc7dealloc)
    *(.text$unlikely$_RNCNCNvNtCs*_7eidolon7runtime3run0s_0B*_)
    *(.text$_RNvXs_NtCs*_7eidolon7minimalNtB*_4HeapNtNtNtCs*_4core5alloc6global11GlobalAlloc5alloc)
    *(.text$_RNvNtCs*_5alloc5boxed14box_new_uninit.91)
    *(.text$_RNCNvNtCs*_7eidolon7runtime3run0B*_)
    *(.text$unlikely$_RNvNtCs*_7eidolon7minimal4fail)
    *(.text$unlikely$_RNvYNvYNtCs*_7eidolon12RuntimeErrorINtNtCs*_4core7convert4FromReE4fromINtNtNtBM_3ops8function6FnOnceTB*_EE9call_onceB*_)
    *(.text$_RNvNtCs*_7eidolon7minimal4exit)
    *(.text$_RNvNtCs*_5alloc5alloc12alloc_zeroed)
    *(.text$_RNvNtCs*_7eidolon7runtime14run_with_synth)
    *(.text$_RNvNtCs*_7eidolon7minimal7decimal)
    *(.text$_RNvNtCs*_7eidolon6assets11framebuffer)
    *(.text$_RNvMNtCs*_7eidolon8graphicsNtB*_8Graphics7loading)
    *(.text$_RNvMs2_NtCs*_5alloc7raw_vecNtB*_11RawVecInner23with_capacity_zeroed_inCs*_7eidolon)
    *(.text$_RNvMs4_NtCs*_5alloc7raw_vecNtB*_11RawVecInner15try_allocate_inB*_)
    *(.text$_RNvMNtCs*_7eidolon8graphicsNtB*_8Graphics4draw)
    *(.text$_RNvNtCs*_7eidolon5audio6render)
    *(.text$_RNvMs_NtCs*_7eidolon6engineNtB*_6Engine8evaluate)
    *(.text$_RNvMNtNtCs*_7eidolon5audio4mathNtB*_6Stereo5lanes)
    *(.text$_RNvCs*_7eidolon5fatal)
    *(.text$_RNvNtNtCs*_7eidolon5audio5graph19eidolon_create_node)
    *(.text$unlikely$_RNvNtCs*_7eidolon5audio5fatal)
    *(.text$_RNvNtNtCs*_7eidolon9synthesis14minimal_worker3run)
    *(.text$_RNvNtNtCs*_7eidolon5audio7runtime8allocate)
    *(.text$_RNvNtCs*_7eidolon8timeline14evaluate_track)
    *(.text$_RINvNtCs*_4core3mem4swapAxj2_ECs*_7eidolon)
    *(.text$_RNvNtNtCs*_7eidolon5audio4math4exp2)
    *(.text$_RNvNtNtCs*_7eidolon5audio4math3sin)
    *(.text$_RNvNtNtCs*_7eidolon5audio3arp8fraction)
    *(.text$_RNvNtNtCs*_7eidolon5audio7runtime8dispatch)
    *(.text$_RNvNtNtCs*_7eidolon5audio5graph20eidolon_create_nodes)
    *(.text$rust_eh_personality)
    *(.text$_RNvNtNtCs*_7eidolon5audio5nodes17eidolon_node_tick)
    *(.text$_RNvNtNtCs*_7eidolon5audio10oscillator4tick)
    *(.text$_RNvNtNtCs*_7eidolon5audio5voice12eidolon_note)
    *(.text$_RNvNtNtCs*_7eidolon5audio3arp5clear)
    *(.text$_RNvNtNtCs*_7eidolon5audio5graph21eidolon_destroy_voice)
    *(.text$_RNvNtNtCs*_7eidolon5audio7effects5write)
    *(.text$_RNvNtNtCs*_7eidolon5audio7effects7advance)
    *(.text$_RNvNtNtCs*_7eidolon5audio6glitch5write)
    *(.text$_RNvNtNtCs*_7eidolon5audio4math6sample)
    *(.text$_RNvNtNtCs*_7eidolon5audio7effects13frequency_map)
    *(.text$eidolon_main)
    *(.text$_RNvNtCs*_7eidolon7minimal7message)
    *(SORT(.text$*))
     *(.text.*)
     *(.gnu.linkonce.t.*)
    *(.glue_7t)
    *(.glue_7)
    KEEP (*(SORT_NONE(.fini)))
    /* ??? Why is .gcc_exc here?  */
     *(.gcc_exc)
    PROVIDE (etext = .);
    PROVIDE (_etext = .);
     KEEP (*(.gcc_except_table))
  }
  .data BLOCK(__section_alignment__) :
  {
    __data_start__ = . ;
    *(.data)
    *(.data2)
    *(SORT(.data$*))
    KEEP(*(.jcr))
    __data_end__ = . ;
    *(.data_cygwin_nocopy)
  }
  .rdata BLOCK(__section_alignment__) :
  {
    *(.rdata$_RNvNtNtCs*_7eidolon5audio10patch_code10MODE_WORDS)
    *(.rdata$_RNvNtNtCs*_7eidolon5audio10patch_code4CODE)
    *(.rdata$_RNvNtCs*_7eidolon7physics7INITIAL)
    *(.rdata$_RNvNtNtCs*_7eidolon5audio10score_code5SCORE)
    *(.rdata$_RNvNtCs*_7eidolon8gl_names8UNIFORMS)
    *(.rd$*)
    *(.rdata)
	     *(SORT(.rdata$*))
    . = ALIGN(4);
    __rt_psrelocs_start = .;
    KEEP(*(.rdata_runtime_pseudo_reloc))
    __rt_psrelocs_end = .;
    /* read-only parts of .didat */
    /* This cannot currently be handled with grouped sections.
	See pe.em:sort_sections.  */
    __DELAY_IMPORT_DIRECTORY_start__ = .;
    KEEP (SORT(*)(.didat$2))
    KEEP (SORT(*)(.didat$3))
    __DELAY_IMPORT_DIRECTORY_end__ = .;
    /* These zeroes mark the end of the import list.  */
    . += (__DELAY_IMPORT_DIRECTORY_end__ - __DELAY_IMPORT_DIRECTORY_start__) ? 8*4 : 0;
    KEEP (SORT(*)(.didat$4))
    KEEP (SORT(*)(.didat$6))
    KEEP (SORT(*)(.didat$7))
    /* .ctors & .dtors */
       /* Note: we always define __CTOR_LIST__ and ___CTOR_LIST__ here,
          we do not PROVIDE them.  This is because the ctors.o startup
	  code in libgcc defines them as common symbols, with the
          expectation that they will be overridden by the definitions
	  here.  If we PROVIDE the symbols then they will not be
	  overridden and global constructors will not be run.
	  See PR 22762 for more details.

	  This does mean that it is not possible for a user to define
	  their own __CTOR_LIST__ and __DTOR_LIST__ symbols; if they do,
	  the content from those variables are included but the symbols
	  defined here silently take precedence.  If they truly need to
	  be redefined, a custom linker script will have to be used.
	  (The custom script can just be a copy of this script with the
	  PROVIDE() qualifiers added).
	  In particular this means that ld -Ur does not work, because
	  the proper __CTOR_LIST__ set by ld -Ur is overridden by a
	  bogus __CTOR_LIST__ set by the final link.  See PR 46.  */
       ___CTOR_LIST__ = .;
       __CTOR_LIST__ = .;
       LONG (-1);
       KEEP(*(.ctors));
       KEEP(*(.ctor));
       KEEP(*(SORT_BY_NAME(.ctors.*)));
       LONG (0);
       /* See comment about __CTOR_LIST__ above.  The same reasoning
          applies here too.  */
       ___DTOR_LIST__ = .;
       __DTOR_LIST__ = .;
       LONG (-1);
       KEEP(*(.dtors));
       KEEP(*(.dtor));
       KEEP(*(SORT_BY_NAME(.dtors.*)));
       LONG (0);
    /* .CRT */
    ___crt_xc_start__ = . ;
    KEEP (*(SORT(.CRT$XC*)))  /* C initialization */
    ___crt_xc_end__ = . ;
    ___crt_xi_start__ = . ;
    KEEP (*(SORT(.CRT$XI*)))  /* C++ initialization */
    ___crt_xi_end__ = . ;
    ___crt_xl_start__ = . ;
    KEEP (*(SORT(.CRT$XL*)))  /* TLS callbacks */
    /* ___crt_xl_end__ is defined in the TLS Directory support code */
    ___crt_xp_start__ = . ;
    KEEP (*(SORT(.CRT$XP*)))  /* Pre-termination */
    ___crt_xp_end__ = . ;
    ___crt_xt_start__ = . ;
    KEEP (*(SORT(.CRT$XT*)))  /* Termination */
    ___crt_xt_end__ = . ;
    ___crt_xd_start__ = . ;
    KEEP (*(SORT(.CRT$XD*)))  /* Dynamic TLS Initializer */
    ___crt_xd_end__ = . ;
  }
  .bss BLOCK(__section_alignment__) :
  {
    __bss_start__ = . ;
    *(.bss)
    *(COMMON)
    __bss_end__ = . ;
  }
  /* The Cygwin32 library uses a section to avoid copying certain data
     on fork.  This used to be named ".data".  The linker used
     to include this between __data_start__ and __data_end__, but that
     breaks building the cygwin32 dll.  Instead, we name the section
     ".data_cygwin_nocopy" and explicitly include it after __data_end__. */
  ___RUNTIME_PSEUDO_RELOC_LIST_END__ = __rt_psrelocs_end;
  __RUNTIME_PSEUDO_RELOC_LIST_END__ = __rt_psrelocs_end;
  ___RUNTIME_PSEUDO_RELOC_LIST__ = __rt_psrelocs_start;
  __RUNTIME_PSEUDO_RELOC_LIST__ = __rt_psrelocs_start;
  .eh_frame BLOCK(__section_alignment__) :
  {
    KEEP(*(.eh_frame*))
  }
  .pdata BLOCK(__section_alignment__) :
  {
    KEEP(*(.pdata*))
  }
  .edata BLOCK(__section_alignment__) :
  {
    *(.edata)
  }
  /DISCARD/ :
  {
    *(.debug$S)
    *(.debug$T)
    *(.debug$F)
     *(.drectve)
     *(.note.GNU-stack)
     *(.gnu.lto_*)
     *(.gnu_object_only)
  }
  .idata BLOCK(__section_alignment__) :
  {
    /* This cannot currently be handled with grouped sections.
	See pe.em:sort_sections.  */
    KEEP (SORT(*)(.idata$2))
    KEEP (SORT(*)(.idata$3))
    /* These zeroes mark the end of the import list.  */
    LONG (0); LONG (0); LONG (0); LONG (0); LONG (0);
    KEEP (SORT(*)(.idata$4))
    __IAT_start__ = .;
    KEEP (SORT(*)(.idata$5))
    __IAT_end__ = .;
    KEEP (SORT(*)(.idata$6))
    KEEP (SORT(*)(.idata$7))
  }
  .didat BLOCK(__section_alignment__) :
  {
    /* This cannot currently be handled with grouped sections.
	See pe.em:sort_sections.  */
    KEEP (SORT(*)(.didat$5))
  }
  /* Windows TLS expects .tls$AAA to be at the start and .tls$ZZZ to be
     at the end of section.  This is important because _tls_start MUST
     be at the beginning of the section to enable SECREL32 relocations with TLS
     data.  */
  .tls BLOCK(__section_alignment__) :
  {
    ___tls_start__ = . ;
    KEEP (*(.tls$AAA))
    KEEP (*(.tls))
    KEEP (*(.tls$))
    KEEP (*(SORT(.tls$*)))
    KEEP (*(.tls$ZZZ))
    ___tls_end__ = . ;
  }
  .endjunk BLOCK(__section_alignment__) :
  {
    /* end is deprecated, don't use it */
    PROVIDE (end = .);
    PROVIDE ( _end = .);
     __end__ = .;
  }
  .rsrc BLOCK(__section_alignment__) : SUBALIGN(4)
  {
    KEEP (*(.rsrc))
    KEEP (*(.rsrc$*))
  }
  .reloc BLOCK(__section_alignment__) :
  {
    *(.reloc)
  }
  .stab BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.stab)
  }
  .stabstr BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.stabstr)
  }
  /* DWARF debug sections.
     Symbols in the DWARF debugging sections are relative to the beginning
     of the section.  Unlike other targets that fake this by putting the
     section VMA at 0, the PE format will not allow it.  */
  /* DWARF 1.1 and DWARF 2.  */
  .debug_aranges BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_aranges)
  }
  .zdebug_aranges BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_aranges)
  }
  .debug_pubnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_pubnames)
  }
  .zdebug_pubnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_pubnames)
  }
  /* DWARF 2.  */
  .debug_info BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_info .gnu.linkonce.wi.*)
  }
  .zdebug_info BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_info .zdebug.gnu.linkonce.wi.*)
  }
  .debug_abbrev BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_abbrev)
  }
  .zdebug_abbrev BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_abbrev)
  }
  .debug_line BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_line)
  }
  .zdebug_line BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_line)
  }
  .debug_frame BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_frame*)
  }
  .zdebug_frame BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_frame*)
  }
  .debug_str BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_str)
  }
  .zdebug_str BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_str)
  }
  .debug_loc BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_loc)
  }
  .zdebug_loc BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_loc)
  }
  .debug_macinfo BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_macinfo)
  }
  .zdebug_macinfo BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_macinfo)
  }
  /* SGI/MIPS DWARF 2 extensions.  */
  .debug_weaknames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_weaknames)
  }
  .zdebug_weaknames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_weaknames)
  }
  .debug_funcnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_funcnames)
  }
  .zdebug_funcnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_funcnames)
  }
  .debug_typenames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_typenames)
  }
  .zdebug_typenames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_typenames)
  }
  .debug_varnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_varnames)
  }
  .zdebug_varnames BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_varnames)
  }
  /* DWARF 3.  */
  .debug_pubtypes BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_pubtypes)
  }
  .zdebug_pubtypes BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_pubtypes)
  }
  .debug_ranges BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_ranges)
  }
  .zdebug_ranges BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_ranges)
  }
  /* DWARF 4.  */
  .debug_types BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_types .gnu.linkonce.wt.*)
  }
  .zdebug_types BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_types .gnu.linkonce.wt.*)
  }
  /* DWARF 5.  */
  .debug_addr BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_addr)
  }
  .zdebug_addr BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_addr)
  }
  .debug_line_str BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_line_str)
  }
  .zdebug_line_str BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_line_str)
  }
  .debug_loclists BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_loclists)
  }
  .zdebug_loclists BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_loclists)
  }
  .debug_macro BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_macro)
  }
  .zdebug_macro BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_macro)
  }
  .debug_names BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_names)
  }
  .zdebug_names BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_names)
  }
  .debug_rnglists BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_rnglists)
  }
  .zdebug_rnglists BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_rnglists)
  }
  .debug_str_offsets BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_str_offsets)
  }
  .zdebug_str_offsets BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_str_offsets)
  }
  .debug_sup BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_sup)
  }
  /* For Go and Rust.  */
  .debug_gdb_scripts BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.debug_gdb_scripts)
  }
  .zdebug_gdb_scripts BLOCK(__section_alignment__) (NOLOAD) :
  {
    *(.zdebug_gdb_scripts)
  }
}
