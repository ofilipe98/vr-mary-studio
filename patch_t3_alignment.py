from pathlib import Path

# 1. Update vrsoft_extractor/mary/antigravity_acp.py
p_acp = Path("vrsoft_extractor/mary/antigravity_acp.py")
raw_acp = p_acp.read_text(encoding="utf-8")
newline_acp = "\r\n" if "\r\n" in raw_acp else "\n"
text_acp = raw_acp.replace("\r\n", "\n")

# A. AcpClient.__init__ recreate isolated temp dir
old_init = """        self.extra_env = extra_env or {}
        self._temp_dir = None
        self.closed = False"""

new_init = """        self.extra_env = extra_env or {}
        try:
            self._temp_dir = tempfile.mkdtemp(prefix="proc-", dir=profile_path())
        except Exception:
            self._temp_dir = None
        self.closed = False"""

assert old_init in text_acp, "old_init not found"
text_acp = text_acp.replace(old_init, new_init, 1)

# Ensure __del__ cleans up temp_dir
old_close = """    def close(self) -> None:"""
new_close = """    def __del__(self) -> None:
        if getattr(self, "_temp_dir", None) and Path(self._temp_dir).is_dir():
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def close(self) -> None:"""

assert old_close in text_acp, "old_close not found"
text_acp = text_acp.replace(old_close, new_close, 1)

# B. extract_acp_models include modelId and name
old_item1 = """                            items.append({
                                "id": model_id,
                                "model": model_id,
                                "displayName": str(name),
                                "description": str(desc),
                                "isDefault": model_id == current_value if current_value is not None else False,
                            })"""

new_item1 = """                            items.append({
                                "id": model_id,
                                "modelId": model_id,
                                "model": model_id,
                                "name": str(name),
                                "displayName": str(name),
                                "description": str(desc),
                                "isDefault": model_id == current_value if current_value is not None else False,
                            })"""

assert old_item1 in text_acp, "old_item1 not found"
text_acp = text_acp.replace(old_item1, new_item1, 1)

old_item2 = """                    items.append({
                        "id": model_id,
                        "model": model_id,
                        "displayName": str(name),
                        "description": str(desc),
                        "isDefault": model_id == current_id if current_id is not None else False,
                    })"""

new_item2 = """                    items.append({
                        "id": model_id,
                        "modelId": model_id,
                        "model": model_id,
                        "name": str(name),
                        "displayName": str(name),
                        "description": str(desc),
                        "isDefault": model_id == current_id if current_id is not None else False,
                    })"""

assert old_item2 in text_acp, "old_item2 not found"
text_acp = text_acp.replace(old_item2, new_item2, 1)

p_acp.write_text(text_acp.replace("\n", newline_acp), encoding="utf-8")
print("antigravity_acp.py updated!")

# 2. Update test_33 in tests/test_antigravity_auth_t3_alignment.py
p_test = Path("tests/test_antigravity_auth_t3_alignment.py")
raw_test = p_test.read_text(encoding="utf-8")
newline_test = "\r\n" if "\r\n" in raw_test else "\n"
text_test = raw_test.replace("\r\n", "\n")

old_test_33 = """# 33. UI action buttons correctly enabled / disabled per lifecycle phase
def test_33_ui_buttons_enabled_disabled_state():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    # Provider available
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp", return_value="agy_acp"):
        bridge.refreshProviders()
        items = bridge.providerItems
        item = next(x for x in items if x["id"] == "antigravity")
        assert item["available"] is True

    # When starting, login should not be allowed again without force
    with patch.object(bridge._antigravity_auth, "_run_login"):
        attempt = bridge._antigravity_auth.start_login()
        assert bridge._antigravity_auth.active_attempt.state == "starting"
        # Re-calling start_login without force reuses attempt (button effectively idempotent)
        assert bridge._antigravity_auth.start_login() is attempt"""

new_test_33 = """# 33. UI action buttons correctly enabled / disabled per lifecycle phase
def test_33_ui_buttons_enabled_disabled_state():
    from vrsoft_extractor.mary.frontend.studio import StudioBridge
    bridge = StudioBridge(settings=MagicMock(), database=MagicMock())

    # Provider available
    with patch("vrsoft_extractor.mary.frontend.studio.resolve_acp", return_value="agy_acp"):
        bridge.refreshProviders()
        items = bridge.providerItems
        item = next(x for x in items if x["id"] == "antigravity")
        assert item["available"] is True

        # When starting, login should not be allowed again without force
        with patch.object(bridge._antigravity_auth, "_run_login"):
            attempt = bridge._antigravity_auth.start_login()
            assert bridge._antigravity_auth.active_attempt.state == "starting"
            # Re-calling start_login without force reuses attempt (button effectively idempotent)
            assert bridge._antigravity_auth.start_login() is attempt"""

assert old_test_33 in text_test, "old_test_33 not found"
text_test = text_test.replace(old_test_33, new_test_33, 1)

p_test.write_text(text_test.replace("\n", newline_test), encoding="utf-8")
print("tests/test_antigravity_auth_t3_alignment.py updated!")
