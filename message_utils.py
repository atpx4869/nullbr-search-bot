def escape_md(text):
    if not text:
        return ""
    escape_chars = r'_*`['
    return "".join(f"\\{char}" if char in escape_chars else char for char in str(text))


def format_resource_blocks(res_list):
    blocks = []
    for item in res_list[:10]:
        file_name = escape_md(item.get('name') or item.get('title', '未命名文件'))
        size = escape_md(str(item.get('size', '未知大小')))
        link = item.get('url') or item.get('link') or item.get('share_link') or item.get('magnet', '')

        res_str = f"大小: {size}"
        resolution = item.get('resolution')
        if resolution:
            res_str += f" 分辨率: {resolution}"

        source = item.get('source')
        if source:
            res_str += f" 来源: {source}"

        quality = item.get('quality')
        if quality:
            if isinstance(quality, list):
                quality = " / ".join(quality)
            res_str += f" 质量: {quality}"

        group = item.get('group')
        if group:
            res_str += f" 发布组: {group}"

        if link and link.startswith('magnet:'):
            blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🧲 磁力链接 (点击复制):\n`{link}`\n")
        else:
            blocks.append(f"📄 *{file_name}*\n{escape_md(res_str)}\n🔗 [点击获取此资源]({link})\n")
    return blocks


def build_resource_message(title, res_list):
    final_text = f"✅ *{escape_md(title)} ({len(res_list)}条)*\n\n" + "\n".join(format_resource_blocks(res_list))
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "...\n(截断)"
    return final_text
