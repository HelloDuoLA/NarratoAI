import streamlit as st
import os
from uuid import uuid4
from loguru import logger
from app.config import config
from app.services import voice
from app.models.schema import AudioVolumeDefaults
from app.utils import utils
from webui.utils.cache import get_songs_cache


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
        try:
            config.save_config()
            logger.info(f"语音设置已保存: {voice_name}")
        except Exception as e:
            logger.error(f"保存语音配置失败: {str(e)}")

    # minimax语音特殊处理
    if "minimax" in selected_friendly_name.lower():
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
        index=1,
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
