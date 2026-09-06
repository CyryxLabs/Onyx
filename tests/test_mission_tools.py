import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.mission_tools import WorkspaceToolError, _open_verified, file_hash, inventory, read_text, search


class WorkspaceMissionToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        (self.root/"notes").mkdir();(self.root/"notes"/"day.md").write_text("Priority: ship Onyx\nsecond",encoding="utf-8")
        (self.root/"binary.bin").write_bytes(b"\0\1\2")
        (self.root/"api_token.txt").write_text("do not read",encoding="utf-8")
        self.env=patch.dict(os.environ,{"ONYX_WORKSPACE_ROOTS":str(self.root)});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_end_to_end_inventory_search_read_hash(self):
        inv=inventory({"root":str(self.root)});self.assertEqual([x["path"] for x in inv["files"]],["binary.bin","notes/day.md"])
        found=search({"root":str(self.root),"query":"ship Onyx"});self.assertEqual(found["matches"][0]["line"],1)
        read=read_text({"root":str(self.root),"path":"notes/day.md"});self.assertIn("Priority",read["text"])
        self.assertEqual(len(file_hash({"root":str(self.root),"path":"notes/day.md"})["sha256"]),64)
    def test_escape_binary_secret_and_limits(self):
        for path in ("../outside.txt",str(self.root/"notes/day.md")):
            with self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":path})
        with self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":"binary.bin"})
        with self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":"api_token.txt"})
        self.assertEqual(len(inventory({"root":str(self.root),"max_files":1})["files"]),1)
        (self.root/"notes"/"control.txt").write_bytes(b"hello\x01world")
        with self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":"notes/control.txt"})
        with self.assertRaises(WorkspaceToolError):search({"root":str(self.root),"query":"(a+)+$","regex":True})

    def test_explicit_roots_required(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaises(WorkspaceToolError):inventory({"root":str(self.root)})

    def test_identity_swap_between_validation_and_open_is_rejected(self):
        target=self.root/"notes"/"day.md";replacement=self.root/"replacement.md";replacement.write_text("replacement",encoding="utf-8")
        original=os.open;swapped=False
        def racing(path,flags,*args,**kwargs):
            nonlocal swapped
            if Path(path)==target and not swapped:os.replace(replacement,target);swapped=True
            return original(path,flags,*args,**kwargs)
        if os.name=="nt":
            def swap(_):os.replace(replacement,target)
            context=patch("core.mission_tools._before_native_open",side_effect=swap)
        else:context=patch("core.mission_tools.os.open",side_effect=racing)
        with context,self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":"notes/day.md"})

    def test_identity_failure_closes_only_owned_descriptor_once(self):
        target=self.root/"notes"/"day.md";replacement=self.root/"replacement.md";replacement.write_text("replacement",encoding="utf-8")
        unrelated=os.open(self.root/"binary.bin",os.O_RDONLY);closed=[];original_close=os.close
        def tracked(fd):closed.append(fd);return original_close(fd)
        def swap(_):os.replace(replacement,target)
        try:
            with patch("core.mission_tools._before_native_open",side_effect=swap),patch("core.mission_tools.os.close",side_effect=tracked),self.assertRaises(WorkspaceToolError):_open_verified(target,1000)
            self.assertEqual(len(closed),1);self.assertNotEqual(closed[0],unrelated);self.assertTrue(os.fstat(unrelated).st_size>=0)
        finally:original_close(unrelated)

    def test_oversize_failure_closes_only_owned_descriptor_once(self):
        target=self.root/"large.txt";target.write_bytes(b"x"*64);unrelated=os.open(self.root/"binary.bin",os.O_RDONLY);closed=[];original_close=os.close
        def tracked(fd):closed.append(fd);return original_close(fd)
        try:
            with patch("core.mission_tools.os.close",side_effect=tracked),self.assertRaises(WorkspaceToolError):_open_verified(target,8)
            self.assertEqual(len(closed),1);self.assertNotEqual(closed[0],unrelated);self.assertTrue(os.fstat(unrelated).st_size>=0)
        finally:original_close(unrelated)
    def test_symlink_is_not_traversed(self):
        link=self.root/"linked"
        try:link.symlink_to(self.root/"notes",target_is_directory=True)
        except OSError:self.skipTest("symlink unavailable")
        self.assertFalse(any(x["path"].startswith("linked") for x in inventory({"root":str(self.root)})["files"]))

    def test_symlink_root_is_rejected(self):
        link=self.root.parent/(self.root.name+"-link")
        try:link.symlink_to(self.root,target_is_directory=True)
        except OSError:self.skipTest("symlink unavailable")
        try:
            with patch.dict(os.environ,{"ONYX_WORKSPACE_ROOTS":str(link)}),self.assertRaises(WorkspaceToolError):inventory({"root":str(link)})
        finally:link.unlink(missing_ok=True)

    def test_intermediate_directory_swap_is_rejected(self):
        outside=Path(self.tmp.name).parent/(Path(self.tmp.name).name+"-outside");outside.mkdir();(outside/"day.md").write_text("external",encoding="utf-8")
        original=self.root/"notes";saved=self.root/"notes-saved"
        def swap(_):
            original.rename(saved);original.symlink_to(outside,target_is_directory=True)
        try:
            with patch("core.mission_tools._before_native_open",side_effect=swap),self.assertRaises(WorkspaceToolError):read_text({"root":str(self.root),"path":"notes/day.md"})
        except OSError:self.skipTest("directory symlink unavailable")
        finally:
            if original.is_symlink():original.unlink()
            if saved.exists():saved.rename(original)
            for p in outside.iterdir():p.unlink()
            outside.rmdir()

    def test_streaming_scandir_has_hard_entry_cap(self):
        class Entry:
            def __init__(self,n):self.path=str(self.root/f"d{n}")
            def is_symlink(self):return False
            def is_dir(self,follow_symlinks=False):return True
            def is_file(self,follow_symlinks=False):return False
        Entry.root=self.root
        class Scan:
            def __enter__(self):return self
            def __iter__(self):return iter(Entry(i) for i in range(20000))
            def __exit__(self,*_):return False
        with patch("core.mission_tools.os.scandir",return_value=Scan()):result=inventory({"root":str(self.root),"max_dirs":500,"max_seconds":10})
        self.assertTrue(result["truncated"]);self.assertEqual(result["reason"],"entry_limit")

if __name__=="__main__":unittest.main()
