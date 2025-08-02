import streamlit as st
import os
import sys
from loguru import logger
from app.config import config
from webui.components import basic_settings, video_settings, audio_settings, subtitle_settings, script_settings, \
    review_settings, merge_settings, system_settings, tts_settings
# from webui.utils import cache, file_utils
from app.utils import utils
from app.utils import ffmpeg_utils
from app.models.schema import VideoClipParams, VideoAspect


# 初始化配置 - 必须是第一个 Streamlit 命令
st.set_page_config(
    page_title="🤖✂️ AI铰剪",
    page_icon="📽️",
    layout="wide",
    initial_sidebar_state="auto",
    # menu_items={
    #     "Report a bug": "https://github.com/linyqh/NarratoAI/issues",
    #     'About': f"# Narrato:blue[AI] :sunglasses: 📽️ \n #### Version: v{config.project_version} \n "
    #              f"自动化影视解说视频详情请移步：https://github.com/linyqh/NarratoAI"
    # },
)

# 设置页面样式
hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 6px; padding-bottom: 10px; padding-left: 20px; padding-right: 20px;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)


def init_log():
    """初始化日志配置"""
    from loguru import logger
    logger.remove()
    _lvl = "DEBUG"

    def format_record(record):
        # 简化日志格式化处理，不尝试按特定字符串过滤torch相关内容
        file_path = record["file"].path
        relative_path = os.path.relpath(file_path, config.root_dir)
        record["file"].path = f"./{relative_path}"
        record['message'] = record['message'].replace(config.root_dir, ".")

        _format = '<green>{time:%Y-%m-%d %H:%M:%S}</> | ' + \
                  '<level>{level}</> | ' + \
                  '"{file.path}:{line}":<blue> {function}</> ' + \
                  '- <level>{message}</>' + "\n"
        return _format

    # 替换为更简单的过滤方式，避免在过滤时访问message内容
    # 此处先不设置复杂的过滤器，等应用启动后再动态添加
    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True
    )

    # 应用启动后，可以再添加更复杂的过滤器
    def setup_advanced_filters():
        """在应用完全启动后设置高级过滤器"""
        try:
            for handler_id in logger._core.handlers:
                logger.remove(handler_id)

            # 重新添加带有高级过滤的处理器
            def advanced_filter(record):
                """更复杂的过滤器，在应用启动后安全使用"""
                ignore_messages = [
                    "Examining the path of torch.classes raised",
                    "torch.cuda.is_available()",
                    "CUDA initialization"
                ]
                return not any(msg in record["message"] for msg in ignore_messages)

            logger.add(
                sys.stdout,
                level=_lvl,
                format=format_record,
                colorize=True,
                filter=advanced_filter
            )
        except Exception as e:
            # 如果过滤器设置失败，确保日志仍然可用
            logger.add(
                sys.stdout,
                level=_lvl,
                format=format_record,
                colorize=True
            )
            logger.error(f"设置高级日志过滤器失败: {e}")

    # 将高级过滤器设置放到启动主逻辑后
    import threading
    threading.Timer(5.0, setup_advanced_filters).start()


def init_global_state():
    """初始化全局状态"""
    if 'video_clip_json' not in st.session_state:
        st.session_state['video_clip_json'] = []
    if 'video_plot' not in st.session_state:
        st.session_state['video_plot'] = ''
    if 'ui_language' not in st.session_state:
        st.session_state['ui_language'] = config.ui.get("language", utils.get_system_locale())
    if 'subclip_videos' not in st.session_state:
        st.session_state['subclip_videos'] = {}


def tr(key):
    """翻译函数"""
    i18n_dir = os.path.join(os.path.dirname(__file__), "webui", "i18n")
    locales = utils.load_locales(i18n_dir)
    loc = locales.get(st.session_state['ui_language'], {})
    return loc.get("Translation", {}).get(key, key)


@st.cache_data
def read_video_file(file_path):
    """缓存视频文件读取，避免重复读取大文件"""
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"读取视频文件失败: {e}")
        return None


@st.cache_data
def read_subtitle_file(file_path):
    """缓存字幕文件读取"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"读取字幕文件失败: {e}")
        return None


def show_download_section(video_files, subtitle_file, tr):
    """显示下载区域的独立函数"""
    if not video_files:
        return
        
    # 创建下载区域
    has_subtitle = subtitle_file and os.path.exists(subtitle_file)
    download_cols = st.columns(2) if has_subtitle else st.columns(1)
    
    # 下载视频文件
    with download_cols[0]:
        st.subheader("📹 " + tr("Download Video"))
        
        if len(video_files) == 1:
            # 单个视频文件
            video_file = video_files[0]
            if not os.path.exists(video_file):
                st.warning(f"视频文件不存在: {os.path.basename(video_file)}")
                return
                
            try:
                file_size = os.path.getsize(video_file) / (1024 * 1024)  # MB
                st.markdown(f"**{os.path.basename(video_file)}** ({file_size:.1f} MB)")
                
                # 读取视频文件数据（使用缓存）
                video_data = read_video_file(video_file)
                if video_data is None:
                    st.error(f"无法读取视频文件: {os.path.basename(video_file)}")
                    return
                
                st.download_button(
                    label=tr('Download Video'),
                    data=video_data,
                    file_name=os.path.basename(video_file),
                    mime="video/mp4",
                    key=f"download_video_single_{hash(video_file)}",
                    use_container_width=True
                )
            except Exception as e:
                logger.error(f"读取视频文件失败: {e}")
                st.error(f"无法读取视频文件: {os.path.basename(video_file)}")
        else:
            # 多个视频文件
            for i, video_file in enumerate(video_files):
                if not os.path.exists(video_file):
                    st.warning(f"视频文件不存在: {os.path.basename(video_file)}")
                    continue
                    
                try:
                    file_size = os.path.getsize(video_file) / (1024 * 1024)  # MB
                    
                    # 创建一个expander来组织多个文件
                    with st.expander(f"视频 {i+1}: {os.path.basename(video_file)} ({file_size:.1f} MB)", expanded=True):
                        # 读取视频文件数据（使用缓存）
                        video_data = read_video_file(video_file)
                        if video_data is None:
                            st.error(f"无法读取视频文件: {os.path.basename(video_file)}")
                            continue
                        
                        st.download_button(
                            label=f"{tr('Download Video')} {i+1}",
                            data=video_data,
                            file_name=os.path.basename(video_file),
                            mime="video/mp4",
                            key=f"download_video_multi_{hash(video_file)}_{i}",
                            use_container_width=True
                        )
                except Exception as e:
                    logger.error(f"读取视频文件失败: {e}")
                    st.error(f"无法读取视频文件: {os.path.basename(video_file)}")
    
    # 下载字幕文件
    if has_subtitle:
        with download_cols[1]:
            st.subheader("📄 " + tr("Download Subtitle"))
            try:
                file_size = os.path.getsize(subtitle_file) / 1024  # KB
                st.markdown(f"**{os.path.basename(subtitle_file)}** ({file_size:.1f} KB)")
                
                # 读取字幕文件数据（使用缓存）
                subtitle_data = read_subtitle_file(subtitle_file)
                if subtitle_data is None:
                    st.error(f"无法读取字幕文件: {os.path.basename(subtitle_file)}")
                    return
                
                st.download_button(
                    label=tr("Download Subtitle"),
                    data=subtitle_data.encode('utf-8'),
                    file_name=os.path.basename(subtitle_file),
                    mime="application/x-subrip",
                    key=f"download_subtitle_{hash(subtitle_file)}",
                    use_container_width=True
                )
                
                # 显示字幕预览
                with st.expander("📖 字幕预览", expanded=False):
                    # 显示前几行字幕作为预览
                    lines = subtitle_data.split('\n')
                    preview_lines = lines[:min(20, len(lines))]
                    st.text('\n'.join(preview_lines))
                    if len(lines) > 20:
                        st.text("...")
                        
            except Exception as e:
                logger.error(f"读取字幕文件失败: {e}")
                st.error(f"无法读取字幕文件: {os.path.basename(subtitle_file)}")


def render_generate_button():
    """渲染生成按钮和处理逻辑"""
    if st.button(tr("Generate Video"), use_container_width=True, type="primary"):
        from app.services import task as tm

        config.save_config()
        task_id = st.session_state.get('task_id')

        if not task_id:
            st.error(tr("请先裁剪视频"))
            return
        if not st.session_state.get('video_clip_json_path'):
            st.error(tr("脚本文件不能为空"))
            return
        if not st.session_state.get('video_origin_path'):
            st.error(tr("视频文件不能为空"))
            return

        st.toast(tr("生成视频"))
        
        # 先创建下载区域占位符（在日志前面显示）
        st.markdown("---")
        st.subheader("📥 生成结果")
        download_placeholder = st.empty()
        with download_placeholder:
            st.info("🔄 视频正在生成中，完成后下载按钮将在此显示...")
        
        # 然后创建日志显示区域（在下载区域后面）
        st.markdown("---")
        st.subheader("📋 处理日志")
        log_container = st.empty()
        log_records = []

        def log_received(msg):
            with log_container:
                log_records.append(msg)
                st.code("\n".join(log_records))

        from loguru import logger
        logger.add(log_received)
        
        logger.info(tr("开始生成视频"))

        # 获取所有参数
        script_params = script_settings.get_script_params()
        video_params = video_settings.get_video_params()
        audio_params = audio_settings.get_audio_params()
        subtitle_params = subtitle_settings.get_subtitle_params()

        # 合并所有参数
        all_params = {
            **script_params,
            **video_params,
            **audio_params,
            **subtitle_params
        }

        # 创建参数对象
        params = VideoClipParams(**all_params)

        result = tm.start_subclip(
            task_id=task_id,
            params=params,
            subclip_path_videos=st.session_state['subclip_videos']
        )

        video_files = result.get("videos", [])
        subtitle_file = result.get("subtitle", None)
        
        # 将结果存储在session_state中，避免刷新丢失
        st.session_state['generated_videos'] = video_files
        st.session_state['generated_subtitle'] = subtitle_file
        
        # 更新下载区域，替换占位符内容
        with download_placeholder:
            st.success(tr("视频生成完成"))
            show_download_section(video_files, subtitle_file, tr)
        
        try:
            if video_files:
                player_cols = st.columns(len(video_files) * 2 + 1)
                for i, url in enumerate(video_files):
                    player_cols[i * 2 + 1].video(url)
        except Exception as e:
            logger.error(f"播放视频失败: {e}")

        # file_utils.open_task_folder(config.root_dir, task_id)
        logger.info(tr("视频生成完成"))

    # 如果有之前生成的结果，也显示下载区域
    elif 'generated_videos' in st.session_state and st.session_state['generated_videos']:
        show_download_section(
            st.session_state['generated_videos'], 
            st.session_state.get('generated_subtitle'), 
            tr
        )


# 全局变量，记录是否已经打印过硬件加速信息
_HAS_LOGGED_HWACCEL_INFO = False

def main():
    """主函数"""
    global _HAS_LOGGED_HWACCEL_INFO
    init_log()
    init_global_state()

    # 检测FFmpeg硬件加速，但只打印一次日志
    hwaccel_info = ffmpeg_utils.detect_hardware_acceleration()
    if not _HAS_LOGGED_HWACCEL_INFO:
        if hwaccel_info["available"]:
            logger.info(f"FFmpeg硬件加速检测结果: 可用 | 类型: {hwaccel_info['type']} | 编码器: {hwaccel_info['encoder']} | 独立显卡: {hwaccel_info['is_dedicated_gpu']} | 参数: {hwaccel_info['hwaccel_args']}")
        else:
            logger.warning(f"FFmpeg硬件加速不可用: {hwaccel_info['message']}, 将使用CPU软件编码")
        _HAS_LOGGED_HWACCEL_INFO = True

    # 仅初始化基本资源，避免过早地加载依赖PyTorch的资源
    # 检查是否能分解utils.init_resources()为基本资源和高级资源(如依赖PyTorch的资源)
    try:
        utils.init_resources()
    except Exception as e:
        logger.warning(f"资源初始化时出现警告: {e}")

    # 使用HTML和CSS来美化标题
    st.markdown("""
    <div style="text-align: left; margin-bottom: 1rem;">
        <h1 style="font-size: 3rem; margin: 0; color: #1f77b4; font-weight: bold;">
            🤖✂️ AI铰剪
        </h1>
        <p style="font-size: 0.9rem; margin: 0; color: #666; margin-top: -0.5rem;">
            <em>AI铰剪 • Powered by NarratoAI</em> 📽️
        </p>
    </div>
    """, unsafe_allow_html=True)
    # st.write(tr("Get Help"))

    # 如果有之前生成的结果，显示清理按钮
    if 'generated_videos' in st.session_state and st.session_state['generated_videos']:
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🗑️ 清理下载区域", help="清除之前生成的下载文件列表"):
                st.session_state.pop('generated_videos', None)
                st.session_state.pop('generated_subtitle', None)
                st.rerun()

    # 首先渲染不依赖PyTorch的UI部分
    # 渲染基础设置面板
    basic_settings.render_basic_settings(tr)
    # 渲染合并设置
    # merge_settings.render_merge_settings(tr)
    # 渲染TTS设置
    tts_settings.render_tts_settings(tr)

    # 渲染主面板
    panel = st.columns(3)
    with panel[0]:
        script_settings.render_script_panel(tr)
    with panel[1]:
        video_settings.render_video_panel(tr)
        audio_settings.render_audio_panel(tr)
    with panel[2]:
        subtitle_settings.render_subtitle_panel(tr)

    # 渲染视频审查面板
    review_settings.render_review_panel(tr)

    # 放到最后渲染可能使用PyTorch的部分
    # 渲染系统设置面板
    with panel[2]:
        system_settings.render_system_panel(tr)

    # 放到最后渲染生成按钮和处理逻辑
    render_generate_button()


if __name__ == "__main__":
    main()
