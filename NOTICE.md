# Attribution and development

WoWDeck Input is an independent Decky plugin maintained by Cody.

The physical keyboard mapping, Steam keyboard integration approach, and bundled evdev_mod are adapted from Chenx Dust's BetterKeyboard (upstream main snapshot downloaded 2026-11-05). The original BSD 3-Clause license and copyright notices are retained in LICENSE. Portions of the upstream Decky template retain Steam Deck Homebrew copyright notices.

The integrated hotkey lifecycle, full-pinyin/Xiaohe settings, configurable shortcut capture, candidate display controls and migration were developed with generative AI assistance, including substantial AI-authored code. Do not claim this project meets the Decky store's restriction against majority AI-generated submissions. Local packaging or a ZIP release is not an official store approval.

No key text, credentials, or user configuration is included in release packages. The plugin does not send keyboard input to a network service.

The opt-in voice feature is an independent client. Its understanding of the Doubao web ASR protocol, trailing silence and web device identifiers is based on lilong7676/doubao-murmur at dbaa4e51cc326e10081d22e3e36dbf7343da4587. See voice/LICENSE-Murmur.txt and https://github.com/lilong7676/doubao-murmur. Upstream describes personal, non-commercial research use. Voice audio goes to Doubao only when dictation is enabled and the user presses the trigger. No project relay or shared developer account is provided.

The optional Wubi 86 table is included unmodified from rime/rime-wubi at revision 152a0d3f3efe40cae216d1e3b338242446848d07. It is a separate, replaceable data file, not part of the BSD-licensed application code. See data/wubi86/AUTHORS, LICENSE (LGPL v3), COPYING.GPL3 and SOURCE.json. The source table, original attribution and license texts are included in both the installation and source archives. The loader and local composer are independently implemented; no Rime engine is bundled.
