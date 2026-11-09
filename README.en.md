# WoWDeck Input 2.0

[简体中文](README.md) | **English**

**Chinese voice input and external keyboard support for World of Warcraft: Forever in Steam Deck Gaming Mode.**

![WoWDeck Input: Chinese voice input and external keyboard support](https://raw.githubusercontent.com/iCodyYang/WoWDeck-Input/main/docs/images/wowdeck-input-2.0-cover.png)

[Download v2.0.0](https://github.com/iCodyYang/WoWDeck-Input/releases/download/v2.0.0/WoWDeck-Input-2.0.0.zip) · [Release files](https://github.com/iCodyYang/WoWDeck-Input/releases/tag/v2.0.0) · [Detailed voice guide (Chinese)](docs/VOICE.md)

WoWDeck Input is a [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin with two independently controlled features:

- **Physical-keyboard Chinese input:** full Pinyin, Xiaohe double Pinyin, and optional Wubi 86. Supports external keyboards and compatible handheld built-in keyboards.
- **Voice input:** sign in with your own Doubao account using a QR code, hold F7 or a mapped back button to speak, then release to fill the game's text field.

**2.0.0 is the major release following public v0.1.3.** It contains the same functionality as the delivered alpha.23 build. The release contains no account sessions or personal settings.

## Install or upgrade

1. Install Decky Loader using its [official instructions](https://github.com/SteamDeckHomebrew/decky-loader#installation). Initial Decky setup may require Desktop Mode; skip this if Decky is already installed.
2. Download **`WoWDeck-Input-2.0.0.zip`**. Do not extract it or choose a `-source` / automatically generated GitHub “Source code” archive.
3. In Gaming Mode, open **… → Decky plug icon → settings cog**. Enable **Developer Mode** under **General**.
4. Open **Developer → Third-party plugins → Install Plugin from ZIP → Browse**, select the ZIP, and confirm. The download link above can also be used for URL installation.
5. Open **WoWDeck Input**, enable **总开关** (master switch), and enable keyboard or voice input as needed.

With Decky installed, plugin setup and QR sign-in stay in Gaming Mode. The plugin is distributed as a ZIP and is not listed in the official Decky Plugin Store. Disable Better Keyboard before enabling this plugin to avoid competing keyboard capture.

Upgrades retain shortcuts, input schemes, appearance and local login data. After upgrading from 0.1.x, check the new master switch; voice requires explicit opt-in. Recent voice previews retain their existing independent switches. No uninstall is required, and Wubi is never selected automatically.

## Voice input: sign in, hold, release

**Voice does not require Ctrl+Space or an external keyboard.**

1. Enable **总开关 → 语音输入 → 启用语音输入** and open **语音设置** (voice settings).
2. Scan the displayed QR using your phone as directed by the login page. Wait for **账号已登录** (signed in) and **就绪** (ready).
3. In the game's Steam Input layout, map a back button such as R5 to keyboard **F7**, using **Regular Press**. Do not configure a long-press trigger, toggle or turbo; the plugin interprets the gestures itself. An external keyboard can send F7 directly.
4. Focus the game's chat input. Hold the button, speak while the waveform is visible, and release. **正在转写** means transcription is finishing; the result is then inserted as an unsent draft.

| Gesture | Action |
| --- | --- |
| Hold F7 / mapped back button | Record |
| Release F7 / mapped back button | Finish recognition and fill the current input; do not submit chat |
| Press again during transcription | Cancel this transcription and insertion |
| Double-tap after insertion | Clear the text just inserted |

Change **听写快捷键** to another available function key if necessary, then update the Steam Input mapping to match. Use **检测背键映射** to diagnose the actual key. A waveform that flashes once may indicate a one-shot mapping instead of Regular Press.

**调整波形位置和透明度** adjusts the waveform position and opacity, including a draggable preview and sliders. Turning off voice or the master switch stops the service and retains login data. **退出登录 → 确认退出** signs out and deletes the plugin's local login profile; scan again to use another account.

Voice-enabled means standby, not continuous recording. Audio is recorded while the trigger is held. Voice needs network access and Doubao's web service; keyboard and Wubi input do not depend on a Doubao account.

### Optional WoW draft clearing

Basic dictation does not need an in-game addon. Double-tap clearing currently supports **World of Warcraft: Forever** through **WoWDeckDraft 0.2.3**:

1. Start the supported game so the plugin can locate its installation.
2. In voice settings, select **安装或更新魔兽双击清空组件**.
3. Fully restart the game to load the addon.
4. After voice text is inserted, double-tap the same dictation key to clear that current unsent draft, then hold to dictate again.

Alternatively, extract `WoWDeckDraft-2.0.0.zip` into the correct game's `Interface/AddOns/` directory. The ZIP follows the main release number; the addon internally remains 0.2.3. Existing 0.2.3 installations need no update.

This is not universal undo or select-all deletion. Sending the message, switching chat fields or changing the draft invalidates the previous draft's clearing eligibility. No persistent Clear or Move buttons appear in the game.

## Physical keyboard input

![In-game Chinese candidate bar](https://raw.githubusercontent.com/iCodyYang/WoWDeck-Input/main/docs/images/wowdeck-input-demo.png)

Open **外接键盘输入法 → 外接键盘设置**. For Pinyin / Xiaohe, check the system Chinese engine and Steam's Simplified Chinese keyboard. If needed, choose **打开 Steam 键盘设置**, then **Steam → Settings → Keyboard → Active Keyboards → Edit → Simplified Chinese (Pinyin)**. Return, choose **重新检测**, and enable **启用外接键盘输入法**.

Focus the game's input field, press and release **Ctrl+Space**, then type. Gaming Mode uses the system IBus engine separately from Desktop Mode's Fcitx configuration.

| Default key | Action |
| --- | --- |
| Ctrl+Space | Open the physical-keyboard input interface |
| Tap either Shift | Switch Chinese / English; Shift+letter still produces uppercase |
| Space or number | Select a candidate |
| F8 | Show candidate position / size / opacity controls; press again to save and hide |
| Esc | Cancel composition / close input |
| Steam+X | Use Steam's original touch keyboard |

Activation and adjustment shortcuts are configurable and cannot conflict with each other or the enabled voice key. Close the input UI before switching schemes. Pinyin scheme changes may affect other applications using the same IBus engine.

### Optional Wubi 86 preview

Select **外接键盘设置 → 中文输入方案 → 五笔 86（试用）**. The bundled offline table loads only when selected. It does not register a system service or modify Pinyin settings.

Use A–Y codes, Space or 1–5 to select, minus/equal or PageUp/PageDown to page, Backspace to edit, and Esc to cancel. Unique four-letter codes commit automatically. Tap Shift for English; Enter commits raw code without submitting chat.

This only affects the plugin's physical-keyboard interface, not Steam's touch keyboard. Wubi 98, New Century, reverse Pinyin lookup and personal frequency learning are not included. Wubi still needs hardware validation; unavailable native interfaces cause a safe exit with a message.

## Compatibility and troubleshooting

The primary development device is a Steam Deck LCD running SteamOS Gaming Mode. Physical keyboard detection covers USB, Bluetooth, PS/2, I2C and SPI. A GPD Win Mini HX 370 user reports that the external-keyboard issue is resolved; this does not validate voice or Wubi on that device. More devices, system images and games need testing. See [validation scope](docs/RELEASE_VALIDATION.md).

For Ctrl+Space issues, use **重新检测键盘（不改变开关）** under the master switch. Check both switches, Steam's Chinese layout, and the actual shortcut. Controllers and virtual keyboard endpoints are excluded to protect menus and avoid duplicate input.

For QR failures, check the network and choose **重新连接账号** or **重新获取二维码** when offered. Failed QR startup stops automatic retries; reconnection does not delete login data. The login page and ASR service can change independently of this project.

Voice requires Qt 6 WebEngine, `parec`, X11, GTK 3 and `xdotool` from the system image. Missing components are reported; the plugin does not modify the read-only system partition. Keyboard input can be used independently.

If text insertion fails, close Steam menus and refocus the game input. Focus changes, clipboard replacement and games that reject the insertion method can all block delivery. The plugin cannot inspect every game's text cursor. See the [voice guide](docs/VOICE.md) for details.

## Privacy, restoration and removal

Keyboard and Wubi input are local. Held-key voice audio is sent to Doubao; there is no shared account or project relay. Login data stays on each user's device. The repository and release packages exclude credentials, recordings, personal settings and device backups. Insertion uses and replaces the clipboard, leaving the newest phrase available to the game. See [Privacy](PRIVACY.md).

Settings can reset the candidate bar or restore the original system Pinyin settings. Uninstall restores Pinyin only if the system still matches the plugin's last applied values. Uninstalling through Decky releases keyboard capture but may retain settings. Sign out first if you want to delete the plugin's login data.

## Development

Requires Node.js, npm and Python 3:

```bash
npm install
npm run typecheck
npm test
npm run build
python3 build_release.py
```

`release/` contains installation, full-source and addon ZIPs, `SHA256SUMS.json` and `RELEASE_AUDIT.json`. Builds use an explicit source allowlist instead of exporting a signed-in device.

## Feedback and licensing

Report device, SteamOS, Decky and plugin versions, keyboard model, game and reproduction steps in [Issues](https://github.com/iCodyYang/WoWDeck-Input/issues). Do not attach login files, personal configuration, chat text or recordings.

Application code uses [BSD 3-Clause](LICENSE). Keyboard integration is based on [BetterKeyboard](https://github.com/chenx-dust/BetterKeyboard), with original notices preserved. Bundled input-device code retains its [python-evdev license](py_modules/evdev_mod/LICENSE.python-evdev). Voice references [Doubao Murmur](https://github.com/lilong7676/doubao-murmur) and retains its [MIT license](voice/LICENSE-Murmur.txt). The separate Rime Wubi data retains [LGPL v3](data/wubi86/LICENSE), [GPL v3](data/wubi86/COPYING.GPL3), authorship and source revision information.

The project uses generative AI assistance; see [NOTICE](NOTICE.md). It is not an official Doubao or Valve plugin.
