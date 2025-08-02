import streamlit as st
import os
import json
import requests
import urllib.parse
from uuid import uuid4
from loguru import logger
from app.config import config
from app.services import voice
from app.models.schema import AudioVolumeDefaults
from app.utils import utils
from webui.utils.cache import get_songs_cache
from .select_high_quality_clips import select_high_quality_clips
from .minimax_clone import clone_voice_minimax


def download_demo_audio(demo_audio_url: str, voice_name: str) -> str:
    """
    下载demo音频文件到本地temp目录
    
    Args:
        demo_audio_url: demo音频的URL
        voice_name: 音色名称，用于创建文件名
    
    Returns:
        本地文件路径，如果下载失败返回None
    """
    try:
        # 创建demo音频保存目录
        demo_audio_dir = os.path.join("storage", "temp", "demo_audio")
        os.makedirs(demo_audio_dir, exist_ok=True)
        
        # 解析URL获取文件扩展名
        parsed_url = urllib.parse.urlparse(demo_audio_url)
        path = parsed_url.path
        file_extension = os.path.splitext(path)[1] or '.mp3'  # 默认为mp3
        
        # 创建本地文件名
        safe_voice_name = "".join(c for c in voice_name if c.isalnum() or c in ('-', '_')).rstrip()
        local_filename = f"{safe_voice_name}_demo_{str(uuid4())[:8]}{file_extension}"
        local_path = os.path.join(demo_audio_dir, local_filename)
        
        # 下载文件
        logger.info(f"开始下载demo音频: {demo_audio_url}")
        response = requests.get(demo_audio_url, stream=True, timeout=30)
        response.raise_for_status()
        
        # 保存到本地
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        file_size = os.path.getsize(local_path) / 1024  # KB
        logger.info(f"demo音频下载成功: {local_path}, 大小: {file_size:.1f} KB")
        return local_path
        
    except Exception as e:
        logger.error(f"下载demo音频失败: {str(e)}")
        return None


def render_audio_panel(tr):
    """渲染音频设置面板"""
    with st.container(border=True):
        st.write(tr("Audio Settings"))

        # 渲染TTS设置
        render_tts_settings(tr)

        # 渲染背景音乐设置
        render_bgm_settings(tr)


def render_tts_settings(tr):
    """渲染TTS(文本转语音)设置"""
    # 获取支持的语音列表
    # 从配置文件读取支持的语言区域，如果没有配置则使用默认值
    support_locales = config.azure.get("support_locales", [
        "zh-CN", "zh-HK", "zh-TW",  # 中文变体
        "en-US"  # 英语
    ])
    # 获取Azure语音列表
    voices = voice.get_all_azure_voices(filter_locals=support_locales)

    # 创建友好的显示名称
    friendly_names = {
        v: v.replace("Female", tr("Female"))
        .replace("Male", tr("Male"))
        .replace("Neural", "")
        for v in voices
    }
    
    minimax_voices_count = 0
    
    # 获取Minimax语音列表
    minimax_voices = config.minimax.get("support_voices", {})
    # 获取Minimax语音数量
    minimax_voices_count = len(minimax_voices)
    if minimax_voices_count > 0:
        friendly_names = {**minimax_voices, **friendly_names}
    

    # 获取保存的语音设置，确定默认选择
    saved_voice_name = config.ui.get("voice_name", "")
    
    # 如果session_state中没有选择，设置默认值
    if "voice_selection" not in st.session_state:
        if saved_voice_name and saved_voice_name in friendly_names:
            # 如果config里有定义且存在，使用config中的
            st.session_state["voice_selection"] = friendly_names[saved_voice_name]
        else:
            # 没有定义则选择与界面语言匹配的非V2版本
            ui_language = st.session_state.get("ui_language", "zh-CN")
            default_voice = None
            for v in friendly_names.keys():
                if v.lower().startswith(ui_language.lower()) and "V2" not in v:
                    default_voice = friendly_names[v]
                    break
            # 如果没找到匹配的，使用第一个
            if default_voice is None and friendly_names:
                default_voice = list(friendly_names.values())[0]
            st.session_state["voice_selection"] = default_voice

    # 语音选择下拉框 - 只使用key，不用index
    selected_friendly_name = st.selectbox(
        tr("Speech Synthesis"),
        options=list(friendly_names.values()),
        key="voice_selection",
    )

    # 获取实际的语音名称
    voice_name = list(friendly_names.keys())[
        list(friendly_names.values()).index(selected_friendly_name)
    ]

    # 如果有切换，马上更新config并持久化保存
    if voice_name != config.ui.get("voice_name", ""):
        config.ui["voice_name"] = voice_name
        
        # 清除demo音频状态，当切换到非自定义音色时
        if "自定义" not in selected_friendly_name:
            if 'show_demo_audio' in st.session_state:
                st.session_state['show_demo_audio'] = False
            if 'demo_audio_url' in st.session_state:
                del st.session_state['demo_audio_url']
            if 'demo_voice_name' in st.session_state:
                del st.session_state['demo_voice_name']
            if 'demo_audio_path' in st.session_state:
                del st.session_state['demo_audio_path']
        
        try:
            config.save_config()
            logger.info(f"语音设置已保存: {voice_name}")
        except Exception as e:
            logger.error(f"保存语音配置失败: {str(e)}")

    # minimax语音特殊处理
    if voice.is_minimax_voice(voice_name):
        render_minimax_settings(tr)
    # Azure V2语音特殊处理
    elif voice.is_azure_v2_voice(voice_name):
        render_azure_v2_settings(tr)

    # 语音参数设置
    render_voice_parameters(tr)

    # 试听按钮
    render_voice_preview(tr, voice_name)


def render_azure_v2_settings(tr):
    """渲染Azure V2语音设置"""
    saved_azure_speech_region = config.azure.get("speech_region", "")
    saved_azure_speech_key = config.azure.get("speech_key", "")

    azure_speech_region = st.text_input(
        tr("Speech Region"),
        value=saved_azure_speech_region
    )
    azure_speech_key = st.text_input(
        tr("Speech Key"),
        value=saved_azure_speech_key,
        type="password"
    )

    config.azure["speech_region"] = azure_speech_region
    config.azure["speech_key"] = azure_speech_key

def render_minimax_settings(tr):
    """渲染minimax语音设置"""
    
    saved_minimax_group_id = config.minimax.get("MINIMAX_GROUP_ID", "")
    saved_minimax_key = config.minimax.get("MINIMAX_KEY", "")

    minimax_group_id = st.text_input(
        tr("group_id"),
        value=saved_minimax_group_id,
        type="password"
    )
    minimax_key = st.text_input(
        tr("API Key"),
        value=saved_minimax_key,
        type="password"
    )

    # 模型选择
    support_models = config.minimax.get("support_models", ["speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"])
    saved_model = config.minimax.get("select_model", "")
    
    # 如果session_state中没有选择，设置默认值
    if "minimax_model_selection" not in st.session_state:
        if saved_model and saved_model in support_models:
            st.session_state["minimax_model_selection"] = saved_model
        else:
            st.session_state["minimax_model_selection"] = support_models[0] if support_models else ""
    
    selected_model = st.selectbox(
        tr("Model"),
        options=support_models,
        key="minimax_model_selection",
    )

    # 语言选择
    support_language_boost = config.minimax.get("support_language_boost", ["Chinese,Yue", "Chinese"])
    saved_language = config.minimax.get("select_language", "")
    
    # 如果session_state中没有选择，设置默认值
    if "minimax_language_selection" not in st.session_state:
        if saved_language and saved_language in support_language_boost:
            st.session_state["minimax_language_selection"] = saved_language
        else:
            st.session_state["minimax_language_selection"] = support_language_boost[0] if support_language_boost else ""
    
    selected_language = st.selectbox(
        tr("Language"),
        options=support_language_boost,
        key="minimax_language_selection",
    )
    
    # TODO:增加音色选择
    # 1. 增加一个按钮进行音色选择
    if "自定义" in st.session_state["voice_selection"]:
        if st.button(tr("音色片段提取")):
            # 清除之前的demo音频状态
            if 'show_demo_audio' in st.session_state:
                st.session_state['show_demo_audio'] = False
            if 'demo_audio_url' in st.session_state:
                del st.session_state['demo_audio_url']
            if 'demo_voice_name' in st.session_state:
                del st.session_state['demo_voice_name']
            if 'demo_audio_path' in st.session_state:
                del st.session_state['demo_audio_path']
                
            # 定义临时目录路径
            TEMP_TTS_DIR = os.path.join("storage", "temp", "TTS")

            # 确保临时目录存在
            os.makedirs(TEMP_TTS_DIR, exist_ok=True)
            video_origin_path = st.session_state['video_origin_path']
            srt_path = st.session_state['subtitle_path']
            video_name = os.path.splitext(os.path.basename(video_origin_path))[0]
            clips_dir = os.path.join(TEMP_TTS_DIR, f"{video_name}_processing", "timbre_clips")
            os.makedirs(clips_dir, exist_ok=True)
            extracted_files = [os.path.join(clips_dir, f) for f in os.listdir(clips_dir) if os.path.isfile(os.path.join(clips_dir, f))]
            audio_path =  os.path.join(TEMP_TTS_DIR, f"{video_name}_processing", f"vocals.wav")
            if len(extracted_files) == 0:
                extracted_files = select_high_quality_clips(
                        srt_file_path=srt_path,
                        video_file_path=audio_path, # TODO:有背景声，还是用人声视频吧
                        output_dir=clips_dir
                    )

            
            # 将提取的文件列表保存到session_state中
            st.session_state['extracted_files'] = extracted_files

        # 音频文件列表展示和播放组件 - 移到按钮点击事件外面，让它始终显示
        if st.session_state.get('extracted_files'):
            # 如果正在显示克隆输入框，则显示克隆界面
            if st.session_state.get('show_clone_input') is not None:
                clone_index = st.session_state.get('show_clone_input')
                audio_path = st.session_state['extracted_files'][clone_index]
                
                st.subheader(f"🎤 {tr('音色克隆')}")
                st.write(f"📁 {tr('选中的音频')}: {os.path.basename(audio_path)}")
                
                # 显示当前选中音频的播放器
                try:
                    with open(audio_path, "rb") as audio_file:
                        audio_bytes = audio_file.read()
                    st.audio(audio_bytes, format="audio/wav")
                except FileNotFoundError:
                    st.error(tr("音频文件未找到"))
                except Exception as e:
                    st.error(f"{tr('播放音频时出错')}: {str(e)}")
                
                st.markdown("---")
                
                # 克隆输入界面
                with st.container():
                    st.write(f"✏️ {tr('为音色克隆起个名字')}:")
                    
                    # 创建三列：输入框和按钮
                    col_input, col_clone, col_cancel = st.columns([3, 1, 1])
                    
                    with col_input:
                        voice_clone_name = st.text_input(
                            tr("音色名称"),
                            key=f"voice_name_input_{clone_index}",
                            placeholder=tr("请输入音色名称")
                        )
                    
                    with col_clone:
                        # 添加空标签来对齐高度
                        st.markdown("&nbsp;", unsafe_allow_html=True)
                        if st.button(tr("开始克隆"), key=f"clone_{clone_index}", use_container_width=True):
                            if voice_clone_name.strip():
                                with st.spinner(tr("正在克隆音色，请稍候...")):
                                    try:
                                        # 调用声音克隆功能
                                        clone_result = clone_voice_minimax(
                                            config=config,
                                            file_path=audio_path,
                                            voice_id=voice_clone_name.strip()
                                        )

                                        # clone_result = True
                                        base_resp = clone_result["base_resp"]
                                        if base_resp.get("status_code") == 0:
                                            demo_audio = clone_result.get("demo_audio", "")
                                            # 构建音色名称（添加-minimax后缀）

                                            voice_key = f"{voice_clone_name.strip()}_minimax"
                                            voice_display_name = f"{voice_clone_name.strip()}-minimax"
                                            
                                            # 添加到配置文件的support_voices中
                                            if "support_voices" not in config.minimax:
                                                config.minimax["support_voices"] = {}
                                            
                                            config.minimax["support_voices"][voice_key] = voice_display_name
        
                                            
                                            # 保存配置文件
                                            try:
                                                config.save_config()
                                                logger.info(f"新音色已添加到配置: {voice_key} = {voice_display_name}")
                                            except Exception as save_error:
                                                logger.error(f"保存配置文件失败: {str(save_error)}")
                                            
                                            st.success(f"🎉 {tr('音色克隆成功')}! {tr('音色名称')}: {voice_display_name}")
                                            st.info(f"✅ {tr('音色已添加到语音选项中，页面将自动刷新以选中新音色')}")
                                            
                                            # 如果有demo音频链接，保存到session_state以便刷新后仍能显示
                                            if demo_audio:
                                                st.session_state['demo_audio_url'] = demo_audio
                                                st.session_state['demo_voice_name'] = voice_clone_name.strip()
                                                st.session_state['show_demo_audio'] = True
                                            
                                            # 清除克隆输入状态
                                            st.session_state['show_clone_input'] = None
                                            
                                            # 延迟刷新页面以避免session_state冲突
                                            import time
                                            time.sleep(2)  # 让用户看到成功信息
                                            st.rerun()
                                        else:
                                            st.error(tr(f"音色克隆失败，请重试 错误码: {base_resp.get('status_code')} 原因: {base_resp.get('status_msg', '未知错误')}"))
                                    except Exception as e:
                                        st.error(f"{tr('克隆过程中出错')}: {str(e)}")
                            else:
                                st.warning(tr("请输入音色名称"))
                    
                    with col_cancel:
                        # 添加空标签来对齐高度
                        st.markdown("&nbsp;", unsafe_allow_html=True)
                        if st.button(tr("返回列表"), key=f"cancel_{clone_index}", use_container_width=True):
                            st.session_state['show_clone_input'] = None
                            st.rerun()
                    
            
            else:
                # 显示音频文件列表
                st.write(tr("音色片段列表"))
                
                # 使用文件列表替换原来的滑块
                selected_audio_index = st.session_state.get('selected_audio_index', 0)
                
                # 创建一个可滚动的容器来显示文件列表
                with st.container():
                    # 使用columns创建一个可滚动的区域
                    scroll_area = st.container(height=250)
                    
                    with scroll_area:
                        # 显示音频文件列表
                        for i, audio_path in enumerate(st.session_state['extracted_files']):
                            # 检查是否是当前选中的音频
                            is_selected = i == st.session_state.get('selected_audio_index', 0)
                            
                            col1, col2, col3 = st.columns([3, 1, 1])
                            
                            with col1:
                                # 如果是选中的音频，高亮显示
                                if is_selected:
                                    st.markdown(f"**🎵 {tr('音频')} {i+1}: {os.path.basename(audio_path)}**")
                                else:
                                    st.write(f"{tr('音频')} {i+1}: {os.path.basename(audio_path)}")
                            
                            with col2:
                                # 播放按钮 - 点击后显示音频播放器
                                if st.button(tr("试听"), key=f"play_{i}"):
                                    st.session_state['selected_audio_index'] = i
                                    st.rerun()  # 立即重新运行以更新显示
                                    
                            with col3:
                                # 选择按钮
                                if st.button(tr("克隆"), key=f"select_{i}"):
                                    st.session_state['selected_audio_index'] = i
                                    st.session_state['show_clone_input'] = i  # 显示克隆输入框
                                    st.rerun()
                            
                            # 显示当前选中音频的播放器
                            if is_selected:
                                try:
                                    with open(audio_path, "rb") as audio_file:
                                        audio_bytes = audio_file.read()
                                    st.audio(audio_bytes, format="audio/wav")
                                    st.markdown("---")  # 分隔线
                                except FileNotFoundError:
                                    st.error(tr("音频文件未找到"))
                                except Exception as e:
                                    st.error(f"{tr('播放音频时出错')}: {str(e)}")
                
                # 显示当前选中的音频文件
                if selected_audio_index < len(st.session_state['extracted_files']):
                    selected_audio_path = st.session_state['extracted_files'][selected_audio_index]
                    st.write(f"{tr('当前选中')}: {os.path.basename(selected_audio_path)}")
        
        elif st.session_state.get('extracted_files') is not None:
            st.info(tr("未找到符合条件的音色片段"))

    # 检查是否有待显示的demo音频
    if st.session_state.get('show_demo_audio') and st.session_state.get('demo_audio_url'):
        demo_audio_url = st.session_state['demo_audio_url']
        demo_voice_name = st.session_state.get('demo_voice_name', 'Unknown')
        
        st.markdown("---")
        st.subheader("🎵 音色克隆演示音频")
        st.write(f"📻 音色名称: **{demo_voice_name}**")
        
        # 检查是否已经下载过这个音频
        demo_audio_path = st.session_state.get('demo_audio_path')
        
        if not demo_audio_path or not os.path.exists(demo_audio_path):
            st.info("🎵 正在下载演示音频...")
            # 下载音频
            demo_audio_path = download_demo_audio(demo_audio_url, demo_voice_name)
            if demo_audio_path:
                st.session_state['demo_audio_path'] = demo_audio_path
        
        # 显示音频播放器
        if demo_audio_path and os.path.exists(demo_audio_path):
            st.success("📻 演示音频下载完成，可以试听新音色效果：")
            try:
                with open(demo_audio_path, "rb") as demo_file:
                    demo_audio_bytes = demo_file.read()
                st.audio(demo_audio_bytes, format="audio/mp3")
            except Exception as audio_error:
                logger.error(f"播放demo音频失败: {str(audio_error)}")
                st.error("演示音频播放失败")
        else:
            st.error("演示音频下载失败")
        
        st.markdown("---")

    # 保存设置
    config.minimax["MINIMAX_GROUP_ID"] = minimax_group_id
    config.minimax["MINIMAX_KEY"] = minimax_key
    
    # 检查并保存模型和语言设置
    if selected_model != config.minimax.get("select_model", ""):
        config.minimax["select_model"] = selected_model
        try:
            config.save_config()
            logger.info(f"Minimax模型设置已保存: {selected_model}")
        except Exception as e:
            logger.error(f"保存Minimax模型设置失败: {str(e)}")
    
    if selected_language != config.minimax.get("select_language", ""):
        config.minimax["select_language"] = selected_language
        try:
            config.save_config()
            logger.info(f"Minimax语言设置已保存: {selected_language}")
        except Exception as e:
            logger.error(f"保存Minimax语言设置失败: {str(e)}")


def render_voice_parameters(tr):
    """渲染语音参数设置"""
    # 音量 - 使用统一的默认值
    voice_volume = st.slider(
        tr("Speech Volume"),
        min_value=AudioVolumeDefaults.MIN_VOLUME,
        max_value=AudioVolumeDefaults.MAX_VOLUME,
        value=AudioVolumeDefaults.VOICE_VOLUME,
        step=0.01,
        help=tr("Adjust the volume of the original audio")
    )
    st.session_state['voice_volume'] = voice_volume


    # 语速
    voice_rate = st.selectbox(
        tr("Speech Rate"),
        options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
        index=2,
    )
    st.session_state['voice_rate'] = voice_rate

    # 音调
    voice_pitch = st.selectbox(
        tr("Speech Pitch"),
        options=[0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0],
        index=2,
    )
    st.session_state['voice_pitch'] = voice_pitch


def render_voice_preview(tr, voice_name):
    """渲染语音试听功能"""
    if st.button(tr("Play Voice")):
        play_content = "感谢关注 NarratoAI，有任何问题或建议，可以关注微信公众号，求助或讨论"
        if not play_content:
            play_content = st.session_state.get('video_script', '')
        if not play_content:
            play_content = tr("Voice Example")

        with st.spinner(tr("Synthesizing Voice")):
            temp_dir = utils.storage_dir("temp", create=True)
            audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")

            sub_maker = voice.tts(
                text=play_content,
                voice_name=voice_name,
                voice_rate=st.session_state.get('voice_rate', 1.0),
                voice_pitch=st.session_state.get('voice_pitch', 1.0),
                voice_file=audio_file,
            )

            # 如果语音文件生成失败，使用默认内容重试
            if not sub_maker:
                play_content = "This is a example voice. if you hear this, the voice synthesis failed with the original content."
                sub_maker = voice.tts(
                    text=play_content,
                    voice_name=voice_name,
                    voice_rate=st.session_state.get('voice_rate', 1.0),
                    voice_pitch=st.session_state.get('voice_pitch', 1.0),
                    voice_file=audio_file,
                )

            # 删除试听文件
            if sub_maker and os.path.exists(audio_file):
                st.audio(audio_file, format="audio/mp3")
                if os.path.exists(audio_file):
                    os.remove(audio_file)


def render_bgm_settings(tr):
    """渲染背景音乐设置"""
    # 背景音乐选项
    bgm_options = [
        (tr("No Background Music"), ""),
        (tr("Random Background Music"), "random"),
        (tr("Custom Background Music"), "custom"),
    ]

    selected_index = st.selectbox(
        tr("Background Music"),
        index=0,
        options=range(len(bgm_options)),
        format_func=lambda x: bgm_options[x][0],
    )

    # 获取选择的背景音乐类型
    bgm_type = bgm_options[selected_index][1]
    st.session_state['bgm_type'] = bgm_type

    # 自定义背景音乐处理
    if bgm_type == "custom":
        custom_bgm_file = st.text_input(tr("Custom Background Music File"))
        if custom_bgm_file and os.path.exists(custom_bgm_file):
            st.session_state['bgm_file'] = custom_bgm_file

    # 背景音乐音量 - 使用统一的默认值
    bgm_volume = st.slider(
        tr("Background Music Volume"),
        min_value=AudioVolumeDefaults.MIN_VOLUME,
        max_value=AudioVolumeDefaults.MAX_VOLUME,
        value=AudioVolumeDefaults.BGM_VOLUME,
        step=0.01,
        help=tr("Adjust the volume of the original audio")
    )
    st.session_state['bgm_volume'] = bgm_volume


def get_audio_params():
    """获取音频参数"""
    return {
        'voice_name': config.ui.get("voice_name", ""),
        'voice_volume': st.session_state.get('voice_volume', AudioVolumeDefaults.VOICE_VOLUME),
        'voice_rate': st.session_state.get('voice_rate', 1.0),
        'voice_pitch': st.session_state.get('voice_pitch', 1.0),
        'bgm_type': st.session_state.get('bgm_type', 'random'),
        'bgm_file': st.session_state.get('bgm_file', ''),
        'bgm_volume': st.session_state.get('bgm_volume', AudioVolumeDefaults.BGM_VOLUME),
    }
