-- voice-assistant：HDMI の音声出力を休止させない。
-- 既定では 5 秒間音を出さないと休止し、休止から戻るたびにモニターが一瞬消えて、その間の音が失われるため。
-- WirePlumber 0.4 用（Raspberry Pi OS bookworm）。tools/setup_pi.sh が ~/.config/wireplumber/main.lua.d/ に置く。
table.insert(alsa_monitor.rules, {
  matches = { { { "node.name", "matches", "alsa_output.*hdmi*" } } },
  apply_properties = { ["session.suspend-timeout-seconds"] = 0 },
})
