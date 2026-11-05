# 安装与首次启用

## 1. 先有 Decky Loader

WoWDeck Input 是 Decky 插件，不能当作普通游戏或桌面软件直接运行。已安装 Decky 的用户跳到第2步。

尚未安装的用户按 Decky 官方说明，在桌面模式下载并运行 Decky 安装程序，建议选择稳定版；安装完成后返回游戏模式。这通常是唯一需要进入桌面的步骤。

官方中文说明：https://github.com/SteamDeckHomebrew/decky-loader/blob/main/README_zh-Hans.md

## 2. 安装 ZIP

1. 把 `WoWDeck-Input-0.1.3.zip` 保存到 SD 上，例如 Downloads（下载）目录。不要解压，不要选择带 `-source` 的源码包。
2. 在游戏模式按右侧“…”打开快捷访问菜单，进入 Decky 插头图标。
3. 打开 Decky 的齿轮设置，在常规页面开启“开发者模式”。这指 Decky 自己的开发者模式，不是 Steam 系统的开发者设置。
4. 进入 Decky“开发者”页面，在“第三方插件”区域找到“从 ZIP 压缩文件安装插件”，点“浏览文件”，选择下载的 ZIP 并确认安装。
5. 返回 Decky 插件列表，打开 WoWDeck Input。
6. 如果已有 Better Keyboard，先在 Decky 中停用它，再启用本插件。无需卸载系统中文引擎或桌面输入法。

官方页面源码及中文文案依据：
https://github.com/SteamDeckHomebrew/decky-loader/blob/main/frontend/src/components/settings/pages/developer/index.tsx
https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/locales/zh-CN.json

## 3. 中文键盘直接在游戏模式启用

路径：**Steam 按钮 → 设置 → 键盘 → 当前键盘/启用的键盘 → 编辑 → 勾选“简体中文（拼音）” → 确认**。不同 Steam 版本的栏目名称可能略有变化。

不需要进入 Linux 桌面，不需要装 Fcitx，不需要输入终端命令。添加的是 Steam 原生键盘布局。

插件的“首次使用检查”分别显示：

- 系统中文引擎是否存在。
- Steam 是否已启用简体中文键盘。

未启用时可点“打开 Steam 键盘设置”，勾选后返回并点“重新检测”。如果 Steam 私有接口变化或暂未就绪，插件显示“无法读取，请手动核对”，不会将“引擎存在”误报为“键盘已启用”。

## 4. 开始使用

启用“输入增强”，新用户默认全拼。小鹤用户在“中文输入方案”中选择“小鹤双拼”即可，系统引擎内置该方案。

在游戏聊天框中 Ctrl＋空格呼出，短按 Shift 切换中英文；默认 F8 调整候选框，再按 F8 保存。默认快捷键可以在插件内录制修改。

0.1.3已在Cody的设备安装，用户确认两项首次使用检查正常；其他新设备的完整安装流程仍待测试，详见VALIDATION.md。
