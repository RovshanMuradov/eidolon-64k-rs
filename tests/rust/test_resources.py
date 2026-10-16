"""Fail-closed syscall reconstruction and resource-origin classification."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools/verify/rust"))
from resources import records,summarize,category
from conformance import DATA
from resource_closure import role


def test_interleaved_fd_transfer_and_mapping_are_resources():
    lines=[
        '10 1.000001 recvmsg(4<UNIX-STREAM:[1]> <unfinished ...>\n',
        '11 1.000002 openat(AT_FDCWD</tmp>, "/tmp/hidden.pcm", O_RDONLY) = 7</tmp/hidden.pcm>\n',
        '10 1.000003 <... recvmsg resumed>, {msg_control=[{cmsg_level=SOL_SOCKET, cmsg_type=SCM_RIGHTS, cmsg_data=[9</tmp/hidden.pcm>]}]}, 0) = 1\n',
        '10 1.000004 mmap(NULL, 100, PROT_READ, MAP_PRIVATE, 9</tmp/hidden.pcm>, 0) = 0x1000\n',
        '10 1.000005 +++ exited with 0 +++\n','11 1.000006 +++ exited with 0 +++\n']
    result=summarize(lines,'/tmp/candidate.exe')
    assert result['inventory']['/tmp/hidden.pcm']['calls']=={'openat':1,'recvmsg':1,'mmap':1}
    assert result['unterminated_pids']==[]


def test_missing_syscall_entry_cannot_pass():
    with pytest.raises(ValueError,match='unpaired'):list(records(['10 1.000003 <... openat resumed>) = 3\n']))


def test_incomplete_live_trace_is_not_complete():
    with pytest.raises(ValueError,match='unterminated'):list(records(['10 1.000003 read(3, <unfinished ...>\n']))


def test_original_reference_input_is_never_a_system_dependency():
    assert category(str(DATA/'reference/native/music.pcm'),'/candidate.exe')=='FORBIDDEN_REFERENCE_INPUT'


def test_successful_async_engine_is_explicitly_unresolved():
    result=summarize(['10 1.000001 io_uring_setup(32, {}) = 3<anon_inode:[io_uring]>\n','10 1.000002 +++ exited with 0 +++\n'],'/candidate.exe')
    assert len(result['successful_async_engines'])==1


def test_successful_open_without_resolved_origin_stays_unresolved():
    result=summarize(['10 1.000001 openat(AT_FDCWD, "hidden.pcm", O_RDONLY) = 3\n','10 1.000002 +++ exited with 0 +++\n'],'/candidate.exe')
    assert len(result['unresolved_successful_opens'])==1


def test_payload_bytes_cannot_invent_file_descriptor_paths():
    result=summarize(['10 1.000001 sendto(4<UNIX-STREAM:[1]>, "123</invented/audio.pcm>", 24, 0, NULL, 0) = 24\n','10 1.000002 +++ exited with 0 +++\n'],'/candidate.exe')
    assert '/invented/audio.pcm' not in result['inventory']


def test_octal_umask_result_is_parsed_without_losing_record():
    result=list(records(['10 1.000001 umask(077) = 022\n','10 1.000002 +++ exited with 0 +++\n']))
    assert result[0]['value']==0o22


def test_system_directory_does_not_allow_external_sound_bank():
    with pytest.raises(ValueError,match='external media'):role('/usr/share/gm.dls',{},'/candidate.exe',DATA/'job')


def test_unknown_user_asset_is_not_runtime_configuration():
    with pytest.raises(ValueError,match='unclassified'):role('/home/rovshan/music-bank.bin',{},'/candidate.exe',DATA/'job')
