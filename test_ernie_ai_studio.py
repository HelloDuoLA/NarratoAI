#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
测试ERNIE AI Studio提供商注册

验证新添加的ERNIE AI Studio提供商是否正确注册和工作
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger
from app.services.llm.config_validator import LLMConfigValidator
from app.services.llm.manager import LLMServiceManager


def test_provider_registration():
    """测试提供商注册"""
    print("\n" + "="*60)
    print("测试ERNIE AI Studio提供商注册")
    print("="*60)
    
    # 测试视觉模型提供商
    vision_providers = LLMServiceManager.list_vision_providers()
    print(f"\n📸 注册的视觉模型提供商: {vision_providers}")
    
    if 'ernie_ai_studio' in vision_providers:
        print("✅ ERNIE AI Studio视觉模型提供商注册成功")
    else:
        print("❌ ERNIE AI Studio视觉模型提供商注册失败")
    
    # 测试文本模型提供商
    text_providers = LLMServiceManager.list_text_providers()
    print(f"\n💬 注册的文本模型提供商: {text_providers}")
    
    if 'ernie_ai_studio' in text_providers:
        print("✅ ERNIE AI Studio文本模型提供商注册成功")
    else:
        print("❌ ERNIE AI Studio文本模型提供商注册失败")


def test_provider_creation():
    """测试提供商实例创建"""
    print(f"\n🔧 测试提供商实例创建...")
    
    try:
        # 测试创建视觉模型提供商
        vision_provider = LLMServiceManager.get_vision_provider('ernie_ai_studio')
        print("✅ ERNIE AI Studio视觉模型提供商实例创建成功")
        print(f"   支持的模型: {vision_provider.supported_models}")
        
    except Exception as e:
        print(f"❌ ERNIE AI Studio视觉模型提供商实例创建失败: {str(e)}")
    
    try:
        # 测试创建文本模型提供商
        text_provider = LLMServiceManager.get_text_provider('ernie_ai_studio')
        print("✅ ERNIE AI Studio文本模型提供商实例创建成功")
        print(f"   支持的模型: {text_provider.supported_models}")
        
    except Exception as e:
        print(f"❌ ERNIE AI Studio文本模型提供商实例创建失败: {str(e)}")


def test_config_validation():
    """测试配置验证"""
    print(f"\n🔍 测试配置验证...")
    
    try:
        # 验证所有配置
        validation_results = LLMConfigValidator.validate_all_configs()
        
        # 检查ERNIE AI Studio相关结果
        if 'ernie_ai_studio' in validation_results.get('vision_providers', {}):
            vision_result = validation_results['vision_providers']['ernie_ai_studio']
            print(f"📸 ERNIE AI Studio视觉模型配置验证: {'✅ 通过' if vision_result['is_valid'] else '❌ 失败'}")
            if vision_result['errors']:
                for error in vision_result['errors']:
                    print(f"   - 错误: {error}")
        
        if 'ernie_ai_studio' in validation_results.get('text_providers', {}):
            text_result = validation_results['text_providers']['ernie_ai_studio']
            print(f"💬 ERNIE AI Studio文本模型配置验证: {'✅ 通过' if text_result['is_valid'] else '❌ 失败'}")
            if text_result['errors']:
                for error in text_result['errors']:
                    print(f"   - 错误: {error}")
        
    except Exception as e:
        print(f"❌ 配置验证失败: {str(e)}")


def test_config_suggestions():
    """测试配置建议"""
    print(f"\n💡 测试配置建议...")
    
    try:
        suggestions = LLMConfigValidator.get_config_suggestions()
        
        if 'ernie_ai_studio' in suggestions.get('vision_providers', {}):
            vision_suggestion = suggestions['vision_providers']['ernie_ai_studio']
            print(f"📸 ERNIE AI Studio视觉模型配置建议:")
            print(f"   必需配置: {vision_suggestion['required_configs']}")
            print(f"   可选配置: {vision_suggestion['optional_configs']}")
            print(f"   示例模型: {vision_suggestion['example_models']}")
        
        if 'ernie_ai_studio' in suggestions.get('text_providers', {}):
            text_suggestion = suggestions['text_providers']['ernie_ai_studio']
            print(f"💬 ERNIE AI Studio文本模型配置建议:")
            print(f"   必需配置: {text_suggestion['required_configs']}")
            print(f"   可选配置: {text_suggestion['optional_configs']}")
            print(f"   示例模型: {text_suggestion['example_models']}")
        
    except Exception as e:
        print(f"❌ 获取配置建议失败: {str(e)}")


def main():
    """主函数"""
    logger.remove()  # 移除默认日志
    
    test_provider_registration()
    test_provider_creation()
    test_config_validation()
    test_config_suggestions()
    
    print("\n" + "="*60)
    print("ERNIE AI Studio提供商测试完成")
    print("="*60)


if __name__ == "__main__":
    main()
