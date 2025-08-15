import os
import sys
import threading
import uuid
import shutil
import zipfile
import re
import datetime
# 延迟导入，直到函数需要时才加载，避免启动时因依赖问题崩溃
# import pandas as pd
# import pypandoc
# import weasyprint
import pathlib
import base64
import mimetypes
import json
import traceback
from flask import Flask, request, jsonify, render_template_string, send_from_directory, Response
from pypdf import PdfReader
from werkzeug.utils import secure_filename

# ==============================================================================
# 全局配置和状态管理
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

TASKS = {}
TASKS_LOCK = threading.Lock()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 设置上传文件大小限制为100MB

# 【v13 个性化增强版】
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title data-i18n-key="html_title">文档转换服务</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
        html, body {
            height: 100%;
            overflow: hidden;
        }
        body {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            font-family: 'Noto Sans SC', sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .main-container {
            width: 100%;
            height: 100%;
            padding: 1rem;
        }
        .card {
            background-color: rgba(255, 255, 255, 0.9);
            backdrop-filter: blur(10px);
            border: none;
            border-radius: 15px;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        .card-body {
            overflow-y: auto;
        }
        .log-container { background-color: #1e1e1e; color: #d4d4d4; font-family: 'SF Mono', 'Courier New', monospace; max-height: 400px; overflow-y: auto; border-radius: 8px; padding: 1rem; border: 1px solid #333; }
        .log-container pre { white-space: pre-wrap; word-break: break-word; margin: 0; font-size: 0.85rem; line-height: 1.6; }
        .progress { height: 2rem; }
        .progress-bar { font-size: 1rem; }
        .btn-convert { background-color: #0d6efd; border: none; padding: 0.75rem 1rem; font-size: 1.1rem; border-radius: 0.5rem; transition: all 0.3s ease; }
        .btn-convert:hover { background-color: #0b5ed7; transform: translateY(-2px); }
        .btn-convert:disabled { background-color: #6c757d; }
        #preview-container { height: 80vh; border: 1px solid #dee2e6; border-radius: 8px; background-color: #f8f9fa; }
        .form-control-color { max-width: 60px; height: calc(1.5em + .75rem + 2px); padding: .375rem; }
        .lang-switcher { position: absolute; top: 1rem; right: 1rem; }
        
        .preview-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(255, 255, 255, 0.85);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10;
            border-radius: 8px;
            backdrop-filter: blur(2px);
        }
    </style>
</head>
<body>
    <div class="main-container">
        <div class="card p-4 p-md-5">
            <div class="lang-switcher btn-group btn-group-sm">
                <button type="button" class="btn btn-outline-secondary" id="lang-zh">中</button>
                <button type="button" class="btn btn-outline-secondary" id="lang-en">EN</button>
            </div>
            <div class="card-body">
                <h2 class="card-title text-center mb-4" data-i18n-key="main_title">云端文件转换中心</h2>
                
                <div class="row gx-5">
                    <div class="col-lg-5">
                        <form id="uploadForm">
                            <fieldset>
                                <legend class="form-label fs-5 mb-3" data-i18n-key="step1_title">1. 选择转换模式</legend>
                                <div class="d-grid gap-3 d-md-flex mb-4">
                                    <input type="radio" class="btn-check" name="mode" id="md-mode" value="markdown" autocomplete="off" checked>
                                    <label class="btn btn-outline-primary w-100 py-2" for="md-mode"><i class="bi bi-markdown me-2"></i>Markdown → PDF</label>
                                    <input type="radio" class="btn-check" name="mode" id="word-mode" value="word" autocomplete="off">
                                    <label class="btn btn-outline-primary w-100 py-2" for="word-mode"><i class="bi bi-file-earmark-word me-2"></i>Word → PDF</label>
                                </div>
                            </fieldset>
                            
                            <fieldset class="mb-4">
                                <legend class="form-label fs-5 mb-3" data-i18n-key="step2_title">2. 上传文件</legend>
                                 <div class="alert alert-info" id="status-message" data-i18n-key="status_initial">选择文件后将开始准备预览。</div>
                                <div class="form-check form-check-inline">
                                    <input class="form-check-input" type="radio" name="upload_type" id="zipRadio" value="zip" checked>
                                    <label class="form-check-label" for="zipRadio" data-i18n-key="upload_zip">上传ZIP压缩包</label>
                                </div>
                                <div class="form-check form-check-inline">
                                    <input class="form-check-input" type="radio" name="upload_type" id="folderRadio" value="folder">
                                    <label class="form-check-label" for="folderRadio" data-i18n-key="upload_folder">上传整个文件夹</label>
                                </div>
                                <div class="mt-3">
                                    <input class="form-control form-control-lg" type="file" id="file_input" name="files">
                                </div>
                            </fieldset>

                            <div id="style-controls">
                                <div id="preview-file-selector-area" class="mb-3" style="display: none;">
                                    <label for="preview_file_select" class="form-label fw-bold" data-i18n-key="select_preview_file">选择预览文件:</label>
                                    <select id="preview_file_select" class="form-select"></select>
                                </div>

                                <fieldset id="style-options-fieldset" class="mt-2">
                                    <legend class="form-label fs-5 mb-3" data-i18n-key="step3_title">3. 自定义样式</legend>
                                    <div class="row g-3">
                                        <!-- ========== UPGRADE: START - 扩充自定义选项 ========== -->
                                        <div class="col-md-6">
                                            <label for="font_family" class="form-label" data-i18n-key="style_font_family">字体</label>
                                            <select id="font_family" class="form-select">
                                                <option value='"Times New Roman", "思源宋体", "Songti SC", serif'>思源宋体 (默认)</option>
                                                <option value='"Helvetica", "Arial", "思源黑体", "Heiti SC", sans-serif'>思源黑体</option>
                                                <option value='"KaiTi", "STKaiti", serif'>楷体</option>
                                                <option value='"FangSong", "STFangsong", serif'>仿宋</option>
                                                <option value='"LiSu", "STLiSu", serif'>隶书</option>
                                                <option value='"Georgia", serif'>Georgia (英文)</option>
                                                <option value='"Garamond", serif'>Garamond (英文)</option>
                                                <option value='"Courier New", monospace'>Courier New (等宽)</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <label for="font_size" class="form-label" data-i18n-key="style_font_size">正文字号</label>
                                            <select id="font_size" class="form-select">
                                                <option value="9pt">9 pt (小)</option>
                                                <option value="10pt">10 pt</option>
                                                <option value="10.5pt">10.5 pt (五号)</option>
                                                <option value="11pt">11 pt</option>
                                                <option value="12pt" selected>12 pt (小四/默认)</option>
                                                <option value="13pt">13 pt</option>
                                                <option value="14pt">14 pt (四号)</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <label for="page_margin" class="form-label" data-i18n-key="style_page_margin">页边距</label>
                                            <select id="page_margin" class="form-select">
                                                <option value="3.0cm">3.0 cm (宽)</option>
                                                <option value="2.54cm" selected>2.54 cm (标准/默认)</option>
                                                <option value="2.2cm">2.2 cm</option>
                                                <option value="2.0cm">2.0 cm (中等)</option>
                                                <option value="1.8cm">1.8 cm</option>
                                                <option value="1.5cm">1.5 cm (窄)</option>
                                                <option value="1.2cm">1.2 cm (极窄)</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <label for="text_align" class="form-label" data-i18n-key="style_text_align">文本对齐</label>
                                            <select id="text_align" class="form-select">
                                                <option value="justify" selected>两端对齐 (默认)</option>
                                                <option value="left">左对齐</option>
                                                <option value="center">居中对齐</option>
                                                <option value="right">右对齐</option>
                                                <option value="start">行首对齐</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <label for="line_height" class="form-label" data-i18n-key="style_line_height">行间距</label>
                                            <select id="line_height" class="form-select">
                                                <option value="1.3">1.3</option>
                                                <option value="1.5">1.5 (单倍行距)</option>
                                                <option value="1.6">1.6</option>
                                                <option value="1.75" selected>1.75 (默认)</option>
                                                <option value="1.8">1.8</option>
                                                <option value="2.0">2.0 (双倍行距)</option>
                                                <option value="2.2">2.2</option>
                                            </select>
                                        </div>
                                        <div class="col-md-6">
                                            <label for="code_theme" class="form-label" data-i18n-key="style_code_theme">代码高亮</label>
                                            <select id="code_theme" class="form-select">
                                                <option value="kate" selected>Kate (默认)</option>
                                                <option value="pygments">Pygments (经典)</option>
                                                <option value="tango">Tango</option>
                                                <option value="espresso">Espresso</option>
                                                <option value="zenburn">Zenburn (暗色)</option>
                                                <option value="monochrome">Monochrome (单色)</option>
                                                <option value="breezedark">Breeze Dark (暗色)</option>
                                                <option value="haddock">Haddock</option>
                                            </select>
                                        </div>
                                        <!-- ========== UPGRADE: END - 扩充自定义选项 ========== -->
                                        <div class="col-md-4 d-flex flex-column"><label for="text_color" class="form-label" data-i18n-key="style_text_color">正文颜色</label><input type="color" id="text_color" class="form-control form-control-color" value="#333333"></div>
                                        <div class="col-md-4 d-flex flex-column"><label for="heading_color" class="form-label" data-i18n-key="style_heading_color">标题颜色</label><input type="color" id="heading_color" class="form-control form-control-color" value="#000000"></div>
                                        <div class="col-md-4 d-flex flex-column"><label for="link_color" class="form-label" data-i18n-key="style_link_color">链接颜色</label><input type="color" id="link_color" class="form-control form-control-color" value="#0d6efd"></div>
                                    </div>
                                </fieldset>
                                <div class="d-grid gap-2 mt-4">
                                    <button type="button" id="previewBtn" class="btn btn-secondary" data-i18n-key="preview_btn" disabled><i class="bi bi-eye-fill me-2"></i>应用样式并预览</button>
                                </div>
                            </div>
                        </form>
                    </div>

                    <div class="col-lg-7">
                        <h3 class="text-center mb-3" data-i18n-key="preview_title">实时预览</h3>
                        <div class="position-relative">
                            <iframe id="preview-container" class="w-100" title="PDF Preview"></iframe>
                            <div id="preview-overlay" class="preview-overlay" style="display: none;">
                                <div class="text-center">
                                    <div class="spinner-border text-primary" role="status">
                                        <span class="visually-hidden">Loading...</span>
                                    </div>
                                    <p class="mt-2 mb-0" data-i18n-key="preview_btn_generating">生成中...</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="d-grid mt-5">
                    <button type="button" id="convertBtn" class="btn btn-convert text-white fw-bold" data-i18n-key="convert_btn" disabled><i class="bi bi-lightning-charge-fill me-2"></i>开始转换</button>
                </div>

                <div id="progress-area" class="mt-5" style="display: none;">
                    <hr class="my-5">
                    <h3 class="text-center mb-4" data-i18n-key="progress_title">转换进度</h3>
                    <div class="progress" role="progressbar">
                        <div id="progress-bar" class="progress-bar progress-bar-striped progress-bar-animated" style="width: 0%;">0%</div>
                    </div>
                    <h4 class="mt-4 mb-3" data-i18n-key="log_title">实时日志</h4>
                    <div id="log-container" class="log-container"></div>
                    <div id="download-area" class="d-grid mt-4" style="display: none;">
                        <a id="download-link" href="#" class="btn btn-success btn-lg" data-i18n-key="download_btn"><i class="bi bi-cloud-download me-2"></i>下载结果</a>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        let currentTaskId = null;
        let currentLang = 'zh';

        const i18n = {
             zh: {
                html_title: "文档转换服务", main_title: "云端文件转换中心",
                step1_title: "1. 选择转换模式", step2_title: "2. 上传文件", step3_title: "3. 自定义样式",
                upload_zip: "上传ZIP压缩包", upload_folder: "上传整个文件夹",
                status_initial: "选择文件后将开始准备预览。", status_preparing: "文件上传和预处理中...",
                status_ready: "✅ 准备就绪！共找到 {count} 个可预览文件。", status_no_md: "⚠️ 上传成功，但未找到可预览的.md文件。",
                status_word_ready: "✅ 上传成功，可以开始转换。", status_error: "❌ 错误: {error}",
                select_preview_file: "选择预览文件:",
                style_font_family: "字体",
                style_font_size: "正文字号", 
                style_page_margin: "页边距",
                style_text_align: "文本对齐",
                style_line_height: "行间距",
                style_code_theme: "代码高亮",
                style_text_color: "正文颜色", style_heading_color: "标题颜色",
                style_link_color: "链接颜色",
                preview_btn: "应用样式并预览", preview_btn_generating: "生成中...",
                preview_title: "实时预览",
                convert_btn: "开始转换", convert_btn_converting: "转换中...",
                progress_title: "转换进度", log_title: "实时日志",
                download_btn: "下载结果",
                alert_no_preview_file: "没有可供预览的文件。",
                alert_preview_error: "预览错误: {error}",
                alert_conversion_start_error: "开始转换失败: {error}"
            },
            en: {
                html_title: "Document Conversion Service", main_title: "Cloud Document Converter",
                step1_title: "1. Select Mode", step2_title: "2. Upload File", step3_title: "3. Customize Style",
                upload_zip: "Upload ZIP", upload_folder: "Upload Folder",
                status_initial: "Select a file to prepare for preview.", status_preparing: "Uploading and processing files...",
                status_ready: "✅ Ready! Found {count} previewable files.", status_no_md: "⚠️ Uploaded, but no previewable .md files found.",
                status_word_ready: "✅ Upload complete. Ready to convert.", status_error: "❌ Error: {error}",
                select_preview_file: "Select file to preview:",
                style_font_family: "Font Family",
                style_font_size: "Font Size",
                style_page_margin: "Page Margin",
                style_text_align: "Text Align",
                style_line_height: "Line Height",
                style_code_theme: "Code Theme",
                style_text_color: "Text Color", style_heading_color: "Heading Color",
                style_link_color: "Link Color",
                preview_btn: "Apply Style & Preview", preview_btn_generating: "Generating...",
                preview_title: "Live Preview",
                convert_btn: "Start Conversion", convert_btn_converting: "Converting...",
                progress_title: "Conversion Progress", log_title: "Live Log",
                download_btn: "Download Result",
                alert_no_preview_file: "No file available for preview.",
                alert_preview_error: "Preview Error: {error}",
                alert_conversion_start_error: "Failed to start conversion: {error}"
            }
        };

        const ui = {
            mdMode: document.getElementById('md-mode'), wordMode: document.getElementById('word-mode'),
            zipRadio: document.getElementById('zipRadio'), folderRadio: document.getElementById('folderRadio'),
            fileInput: document.getElementById('file_input'), styleControls: document.getElementById('style-controls'),
            previewFileSelectorArea: document.getElementById('preview-file-selector-area'),
            previewFileSelect: document.getElementById('preview_file_select'), previewBtn: document.getElementById('previewBtn'),
            convertBtn: document.getElementById('convertBtn'), statusMessage: document.getElementById('status-message'),
            previewContainer: document.getElementById('preview-container'),
            progressArea: document.getElementById('progress-area'), progressBar: document.getElementById('progress-bar'),
            logContainer: document.getElementById('log-container'), downloadArea: document.getElementById('download-area'),
            downloadLink: document.getElementById('download-link'),
            langZhBtn: document.getElementById('lang-zh'), langEnBtn: document.getElementById('lang-en'),
            previewOverlay: document.getElementById('preview-overlay')
        };

        function updateLanguage(lang) {
            currentLang = lang;
            document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
            ui.langZhBtn.classList.toggle('active', lang === 'zh');
            ui.langEnBtn.classList.toggle('active', lang === 'en');
            document.querySelectorAll('[data-i18n-key]').forEach(el => {
                const key = el.getAttribute('data-i18n-key');
                const text = i18n[lang][key];
                if (text) {
                    if (el.tagName === 'BUTTON' || el.tagName === 'A') {
                        const icon = el.querySelector('i');
                        if (icon) {
                            el.innerHTML = icon.outerHTML + ' ' + text;
                        } else {
                            el.textContent = text;
                        }
                    } else {
                         el.textContent = text;
                    }
                }
            });
        }
        
        ui.langZhBtn.addEventListener('click', () => updateLanguage('zh'));
        ui.langEnBtn.addEventListener('click', () => updateLanguage('en'));

        document.querySelectorAll('#style-options-fieldset select, #style-options-fieldset input[type="color"]').forEach(el => {
            el.addEventListener('change', () => { if(!ui.previewBtn.disabled) { generatePreview(); }});
        });

        ui.mdMode.addEventListener('change', updateUiForMode);
        ui.wordMode.addEventListener('change', updateUiForMode);
        ui.zipRadio.addEventListener('change', toggleUploadMode);
        ui.folderRadio.addEventListener('change', toggleUploadMode);
        ui.fileInput.addEventListener('change', handleFileSelection);
        ui.previewBtn.addEventListener('click', generatePreview);
        ui.convertBtn.addEventListener('click', startConversion);
        ui.previewFileSelect.addEventListener('change', generatePreview);

        function getStyleOptions() {
            const elements = document.querySelectorAll('#style-options-fieldset select, #style-options-fieldset input');
            const options = {};
            elements.forEach(el => options[el.id] = el.value);
            return options;
        }

        function updateUiForMode() {
            const isMdMode = ui.mdMode.checked;
            ui.styleControls.style.display = isMdMode ? 'block' : 'none';
            document.querySelector('#preview-container').parentElement.style.display = isMdMode ? 'block' : 'none';
            toggleUploadMode();
        }

        function toggleUploadMode() {
            if (ui.folderRadio.checked) {
                ui.fileInput.webkitdirectory = true; ui.fileInput.directory = true; ui.fileInput.multiple = true; ui.fileInput.accept = '';
            } else {
                ui.fileInput.webkitdirectory = false; ui.fileInput.directory = false; ui.fileInput.multiple = false; ui.fileInput.accept = '.zip';
            }
            resetState();
        }
        
        function resetState() {
            currentTaskId = null;
            ui.fileInput.value = '';
            ui.previewBtn.disabled = true;
            ui.convertBtn.disabled = true;
            ui.statusMessage.textContent = i18n[currentLang].status_initial;
            ui.statusMessage.className = 'alert alert-info';
            ui.previewContainer.src = 'about:blank';
            ui.previewFileSelectorArea.style.display = 'none';
            ui.progressArea.style.display = 'none';
        }

        async function handleFileSelection(event) {
            const isMdMode = ui.mdMode.checked;
            const formData = new FormData();
            formData.append('mode', isMdMode ? 'markdown' : 'word');
            formData.append('upload_type', ui.zipRadio.checked ? 'zip' : 'folder');

            if (!ui.fileInput.files || ui.fileInput.files.length === 0) return;

            if (ui.zipRadio.checked) {
                formData.append('zipfile', ui.fileInput.files[0]);
            } else {
                for (const file of ui.fileInput.files) { formData.append('files[]', file, file.webkitRelativePath); }
            }

            ui.statusMessage.textContent = i18n[currentLang].status_preparing;
            ui.statusMessage.className = 'alert alert-warning';
            ui.previewBtn.disabled = true;
            ui.convertBtn.disabled = true;
            ui.previewFileSelectorArea.style.display = 'none';

            try {
                const response = await fetch('/prepare_upload', { method: 'POST', body: formData });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Server failed to prepare files');

                currentTaskId = data.task_id;
                ui.convertBtn.disabled = false;
                
                if (isMdMode && data.preview_files && data.preview_files.length > 0) {
                    ui.statusMessage.textContent = i18n[currentLang].status_ready.replace('{count}', data.preview_files.length);
                    ui.statusMessage.className = 'alert alert-success';
                    
                    ui.previewFileSelect.innerHTML = '';
                    data.preview_files.forEach(file => {
                        const option = document.createElement('option');
                        option.value = file; option.textContent = file;
                        ui.previewFileSelect.appendChild(option);
                    });
                    ui.previewFileSelectorArea.style.display = 'block';
                    ui.previewBtn.disabled = false;
                    generatePreview();
                } else if (isMdMode) {
                    ui.statusMessage.textContent = i18n[currentLang].status_no_md;
                    ui.statusMessage.className = 'alert alert-warning';
                } else {
                    ui.statusMessage.textContent = i18n[currentLang].status_word_ready;
                    ui.statusMessage.className = 'alert alert-success';
                }
            } catch (error) {
                ui.statusMessage.textContent = i18n[currentLang].status_error.replace('{error}', error.message);
                ui.statusMessage.className = 'alert alert-danger';
                resetState();
            }
        }
        
        async function generatePreview() {
            if (!currentTaskId || !ui.previewFileSelect.value) {
                alert(i18n[currentLang].alert_no_preview_file);
                return;
            }

            ui.previewOverlay.style.display = 'flex';
            ui.previewBtn.disabled = true;

            try {
                const payload = {
                    task_id: currentTaskId,
                    style_options: getStyleOptions(),
                    preview_file: ui.previewFileSelect.value
                };

                const response = await fetch('/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(errorText || 'Preview generation failed');
                }
                
                const blob = await response.blob();
                const pdfUrl = URL.createObjectURL(blob);

                ui.previewContainer.onload = function() {
                    ui.previewOverlay.style.display = 'none';
                    ui.previewContainer.onload = null;
                };

                ui.previewContainer.src = pdfUrl;

            } catch (error) {
                alert(i18n[currentLang].alert_preview_error.replace('{error}', error.message));
                ui.previewContainer.src = 'about:blank';
                ui.previewOverlay.style.display = 'none';
            } finally {
                ui.previewBtn.disabled = false;
            }
        }

        function startConversion() {
            if (!currentTaskId) return;
            ui.convertBtn.disabled = true;
            ui.convertBtn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${i18n[currentLang].convert_btn_converting}`;
            ui.progressArea.style.display = 'block';
            ui.logContainer.innerHTML = '';
            ui.downloadArea.style.display = 'none';
            ui.progressBar.style.width = '0%';
            ui.progressBar.textContent = '0%';
            ui.progressBar.classList.remove('bg-danger', 'bg-success');
            
            fetch('/start_conversion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: currentTaskId, style_options: ui.mdMode.checked ? getStyleOptions() : {} })
            })
            .then(res => res.json())
            .then(data => {
                if (data.error) throw new Error(data.error);
                appendLog({ log: `转换任务已开始, ID: ${data.task_id}`, is_diag: false });
                pollStatus(data.task_id);
            })
            .catch(error => {
                alert(i18n[currentLang].alert_conversion_start_error.replace('{error}', error.message));
                ui.convertBtn.disabled = false;
                ui.convertBtn.innerHTML = `<i class="bi bi-lightning-charge-fill me-2"></i> ${i18n[currentLang].convert_btn}`;
            });
        }
        
        function pollStatus(taskId) {
            const interval = setInterval(() => {
                fetch(`/status/${taskId}`)
                .then(res => res.json())
                .then(statusData => {
                    ui.progressBar.style.width = statusData.progress + '%';
                    ui.progressBar.textContent = statusData.progress + '%';
                    if (statusData.logs && statusData.logs.length > 0) {
                         statusData.logs.forEach(logEntry => appendLog(logEntry));
                    }
                    if (statusData.state === 'SUCCESS' || statusData.state === 'FAILURE') {
                        clearInterval(interval);
                        ui.convertBtn.disabled = false;
                        ui.convertBtn.innerHTML = `<i class="bi bi-lightning-charge-fill me-2"></i> ${i18n[currentLang].convert_btn}`;
                        if (statusData.state === 'SUCCESS') {
                            ui.progressBar.classList.add('bg-success');
                            ui.downloadLink.href = statusData.result_url;
                            ui.downloadArea.style.display = 'block';
                        } else {
                            ui.progressBar.classList.add('bg-danger');
                        }
                    }
                });
            }, 1500);
        }

        function appendLog(logEntry) {
            const pre = document.createElement('pre');
            pre.className = logEntry.is_diag ? 'diag-log' : 'main-log';
            if (logEntry.log.includes("🎉")) { pre.className = 'success-log'; }
            else if (logEntry.log.includes("❌")) { pre.className = 'error-log'; }
            else if (logEntry.log.includes("任务已开始")) { pre.className = 'info-log'; }
            pre.textContent = `> ${logEntry.log}`;
            ui.logContainer.appendChild(pre);
            ui.logContainer.scrollTop = ui.logContainer.scrollHeight;
        }

        // 初始化
        const browserLang = navigator.language || navigator.userLanguage;
        updateLanguage(browserLang.toLowerCase().startsWith('zh') ? 'zh' : 'en');
        updateUiForMode();
    });
    </script>
</body>
</html>
"""

# ==============================================================================
# 后端核心转换逻辑 (无变化)
# ==============================================================================

@app.errorhandler(Exception)
def handle_global_exception(e):
    print("="*20 + " 全局异常处理器捕获到错误 " + "="*20)
    traceback.print_exc()
    print("="*70)
    if hasattr(e, 'code'):
        return jsonify(error=f"HTTP异常: {e.name}", message=e.description), e.code
    return jsonify(error="服务器发生了一个未处理的内部错误，请查看后台日志。"), 500

@app.route('/favicon.ico')
def favicon():
    return '', 204

def read_file_with_fallback(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except UnicodeDecodeError:
        print(f"      [LOG] 文件 {os.path.basename(file_path)} 不是UTF-8编码，尝试使用GBK编码...")
        with open(file_path, 'r', encoding='gbk', errors='ignore') as f:
            return f.read()
    except Exception as e:
        print(f"      [ERROR] 读取文件 {os.path.basename(file_path)} 时发生未知错误: {e}")
        raise

def update_task_status(task_id, state, progress=None, log=None, error=None, result_url=None, is_diag=False, preview_files=None):
    with TASKS_LOCK:
        if task_id not in TASKS: TASKS[task_id] = {}
        task = TASKS[task_id]
        task['state'] = state
        if progress is not None: task['progress'] = progress
        if log: task.setdefault('logs', []).append({'log': log, 'is_diag': is_diag})
        if error: task.setdefault('logs', []).append({'log': f"❌ 任务失败: {error}", 'is_diag': False}); task['error'] = error
        if result_url: task['result_url'] = result_url
        if preview_files is not None: task['preview_files'] = preview_files

def get_and_clear_logs(task_id):
    with TASKS_LOCK:
        logs = TASKS.get(task_id, {}).get('logs', [])
        if logs: TASKS[task_id]['logs'] = []
        return logs

def get_pdf_page_count(pdf_file_path):
    try:
        with open(pdf_file_path, 'rb') as f: return len(PdfReader(f).pages)
    except Exception: return '无法读取'

def preprocess_markdown_images(md_content, md_file_dir):
    def replacer(match):
        alt_text, link = match.group(1), match.group(2)
        if link.startswith(('http://', 'https://', 'data:image')): return match.group(0)
        clean_link = link.split('?')[0].split('#')[0]
        absolute_image_path = os.path.normpath(os.path.join(md_file_dir, clean_link))
        if os.path.exists(absolute_image_path):
            mime_type, _ = mimetypes.guess_type(absolute_image_path)
            if not mime_type: mime_type = 'application/octet-stream'
            with open(absolute_image_path, 'rb') as f: img_data = f.read()
            base64_data = base64.b64encode(img_data).decode('utf-8')
            return f'![{alt_text}](data:{mime_type};base64,{base64_data})'
        return match.group(0)
    return re.sub(r'!\[(.*?)\]\((.*?)\)', replacer, md_content)

def get_css_style(style_options):
    defaults = {'font_family': '"Times New Roman", "思源宋体", "Songti SC", serif', 'font_size': '12pt', 'page_margin': '2.54cm', 'line_height': '1.75', 'text_align': 'justify', 'text_color': '#333333', 'heading_color': '#000000', 'link_color': '#0d6efd'}
    def get_opt(key): return style_options.get(key, defaults[key])
    return f"""@page {{ size: A4; margin: {get_opt('page_margin')}; }} html {{ font-size: {get_opt('font_size')}; }} body {{ font-family: {get_opt('font_family')}; line-height: {get_opt('line_height')}; color: {get_opt('text_color')}; text-align: {get_opt('text_align')}; }} a {{ color: {get_opt('link_color')}; text-decoration: none; }} a:hover {{ text-decoration: underline; }} .markdown-body {{ box-sizing: border-box; width: 100%; max-width: 1200px; margin: 0 auto; padding: 0; }} h1,h2,h3,h4,h5,h6 {{ font-family: "Helvetica", "Arial", "Microsoft YaHei", sans-serif; font-weight: 700; margin-top: 2em; margin-bottom: 1em; color: {get_opt('heading_color')}; line-height: 1.3; text-align: left; }} h1 {{ font-size: 24pt; border-bottom: 2px solid {get_opt('heading_color')}; padding-bottom: .2em; }} h2 {{ font-size: 18pt; border-bottom: 1px solid #ccc; padding-bottom: .2em; }} h3 {{ font-size: 14pt; }} p {{ margin-top: 0; margin-bottom: 1.2em; }} img {{ max-width: 100%; height: auto; display: block; margin: 1.5em auto; border: 1px solid #ddd; padding: 4px; border-radius: 4px; }} blockquote {{ margin: 1.5em 0; padding: .5em 1.5em; color: #555; background-color: #f9f9f9; border-left: 5px solid #ccc; }} table {{ width: 100%; border-collapse: collapse; margin: 1.5em 0; display: table; }} th,td {{ border: 1px solid #ccc; padding: .75em; text-align: left; }} th {{ background-color: #f2f2f2; font-weight: 700; }} ul,ol {{ padding-left: 2em; margin-bottom: 1.2em; }} pre {{ background-color: #f6f8fa; border: 1px solid #d1d5da; border-radius: 6px; padding: 16px; overflow: auto; font-size: 85%; line-height: 1.45; }} code,tt {{ font-family: "SFMono-Regular",Consolas,"Liberation Mono",Menlo,Courier,monospace; font-size: 90%; }} pre>code {{ padding: 0; margin: 0; background-color: transparent; border: 0; }}"""

def unzip_with_encoding_fix(zip_path, extract_dir):
    print(f"      [LOG] 开始解压ZIP文件: {zip_path}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for member in zip_ref.infolist():
            try: filename_decoded = member.filename.encode('cp437').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                try: filename_decoded = member.filename.encode('cp437').decode('gbk')
                except Exception: filename_decoded = member.filename
            
            if filename_decoded.startswith('__MACOSX/'):
                print(f"        [LOG] 跳过macOS元数据目录: {filename_decoded}")
                continue

            member.filename = filename_decoded
            target_path = os.path.join(extract_dir, member.filename)
            print(f"        [LOG] 正在解压: {member.filename} -> {target_path}")
            if not os.path.realpath(target_path).startswith(os.path.realpath(extract_dir)):
                print(f"        [ERROR] 检测到非法的文件路径，跳过解压: {member.filename}")
                continue
            if member.is_dir():
                os.makedirs(target_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with zip_ref.open(member, 'r') as source, open(target_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
    print(f"      [LOG] ZIP文件解压完成。")

def run_conversion_thread(task_id, style_options=None):
    import pandas as pd
    import pypandoc
    import weasyprint

    if style_options is None: style_options = {}
    with TASKS_LOCK:
        task_info = TASKS.get(task_id)
        if not task_info: return
        task_dir, mode = task_info['task_dir'], task_info['mode']
    
    print(f"\n[TASK {task_id}] ==> 开始执行转换线程...")
    try:
        source_dir, result_dir = os.path.join(task_dir, 'source'), os.path.join(task_dir, 'result')
        file_extensions = ('.docx', '.doc') if mode == 'word' else ('.md',)
        print(f"[TASK {task_id}] 扫描源目录 {source_dir}，查找 {file_extensions} 文件...")
        
        all_files_found = []
        for dp, dn, fn in os.walk(source_dir):
            if '__MACOSX' in dp.split(os.sep): continue
            for f in fn:
                if f.startswith('._'): continue
                if f.lower().endswith(file_extensions): all_files_found.append(os.path.join(dp, f))
        
        if not all_files_found: raise ValueError(f"未找到有效的 {file_extensions} 文件。")
        
        print(f"[TASK {task_id}] 共找到 {len(all_files_found)} 个有效文件待转换。")
        files_to_convert, report_results, total_files = sorted(list(set(all_files_found))), [], len(all_files_found)
        custom_css = weasyprint.CSS(string=get_css_style(style_options)) if mode == 'markdown' else None
        if mode == 'markdown': print(f"[TASK {task_id}] 已生成自定义CSS样式。")

        for i, file_path in enumerate(files_to_convert):
            filename = os.path.relpath(file_path, source_dir)
            progress = 10 + int((i / total_files) * 80)
            update_task_status(task_id, 'PROGRESS', progress=progress, log=f"({i+1}/{total_files}) 正在处理: {filename}")
            print(f"[TASK {task_id}] ({i+1}/{total_files}) 正在处理: {filename}")
            
            rel_path = os.path.relpath(file_path, source_dir)
            pdf_path = os.path.join(result_dir, os.path.splitext(rel_path)[0] + '.pdf')
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

            if mode == 'markdown':
                md_content = read_file_with_fallback(file_path)
                processed_md = preprocess_markdown_images(md_content, os.path.dirname(file_path))
                html_body = pypandoc.convert_text(source=processed_md, to='html', format='markdown+latex_macros', extra_args=[f'--highlight-style={style_options.get("code_theme", "kate")}'])
                full_html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body><article class="markdown-body">{html_body}</article></body></html>'
                weasyprint.HTML(string=full_html).write_pdf(pdf_path, stylesheets=[custom_css])
            else:
                pypandoc.convert_file(file_path, 'pdf', outputfile=pdf_path, extra_args=['--pdf-engine=xelatex', '-V', 'mainfont=Microsoft YaHei'])

            page_count = get_pdf_page_count(pdf_path)
            category = pathlib.Path(rel_path).parts[0] if len(pathlib.Path(rel_path).parts) > 1 else '根目录'
            report_results.append({"大目录": category, "文件名": pathlib.Path(file_path).stem, "页数": page_count})
            print(f"      [LOG] 文件 {filename} 处理完成，共 {page_count} 页。")

        if report_results:
            update_task_status(task_id, 'PROGRESS', progress=95, log="生成汇总报告...")
            pd.DataFrame(report_results).to_csv(os.path.join(result_dir, "转换结果汇总.csv"), index=False, encoding='utf_8_sig')

        update_task_status(task_id, 'PROGRESS', progress=98, log="压缩结果...")
        zip_filename = f"转换结果_{task_id[:8]}.zip"
        zip_path = os.path.join(task_dir, zip_filename)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(result_dir):
                for file in files:
                    zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), result_dir))
        
        print(f"[TASK {task_id}] ==> 转换线程成功完成。")
        update_task_status(task_id, 'SUCCESS', progress=100, log="🎉 任务成功！可以下载文件了。", result_url=f"/download/{task_id}")

    except Exception as e:
        print(f"[TASK {task_id}] 错误: 转换线程中发生异常！")
        traceback.print_exc()
        update_task_status(task_id, 'FAILURE', error=str(e))

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/prepare_upload', methods=['POST'])
def prepare_upload():
    print(f"\n[LOG] ==> /prepare_upload 路由被触发...")
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(OUTPUT_DIR, task_id)
    
    print(f"[TASK {task_id}] 1. 创建任务目录: {task_dir}")
    source_dir = os.path.join(task_dir, 'source')
    os.makedirs(source_dir, exist_ok=True)
    mode = request.form.get('mode', 'markdown')
    upload_type = request.form.get('upload_type')
    with TASKS_LOCK: TASKS[task_id] = {'task_dir': task_dir, 'mode': mode, 'state': 'PREPARING'}
    print(f"[TASK {task_id}] 2. 模式: {mode}, 上传类型: {upload_type}")
    
    print(f"[TASK {task_id}] 3. 开始处理上传的文件...")
    if upload_type == 'folder':
        files = request.files.getlist("files[]")
        if not files: return jsonify({'error': '未选择任何文件夹内容'}), 400
        print(f"      [LOG] 收到 {len(files)} 个文件。")
        for file in files:
            relative_path = file.filename or ""
            if not relative_path: continue
            normalized_path = os.path.normpath(relative_path)
            if ".." in normalized_path.split(os.sep): continue
            destination_path = os.path.join(source_dir, normalized_path)
            if not os.path.abspath(destination_path).startswith(os.path.abspath(source_dir)): continue
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            print(f"      [LOG] 正在保存: {relative_path} -> {destination_path}")
            file.save(destination_path)
    else: # zip
        file = request.files.get('zipfile')
        if not file or not file.filename.endswith('.zip'): return jsonify({'error': '请上传一个ZIP文件'}), 400
        zip_path = os.path.join(task_dir, 'source.zip')
        print(f"      [LOG] 正在保存ZIP文件到: {zip_path}")
        file.save(zip_path)
        unzip_with_encoding_fix(zip_path, source_dir)
    
    print(f"[TASK {task_id}] 4. 文件保存/解压完成，开始查找可预览的文件...")
    preview_files = []
    if mode == 'markdown':
        for dp, _, fn in os.walk(source_dir):
            if '__MACOSX' in dp.split(os.sep): continue
            for f in sorted(fn):
                if f.startswith('._'): continue
                if f.lower().endswith('.md'):
                    preview_files.append(os.path.relpath(os.path.join(dp, f), source_dir))
    
    if preview_files: print(f"      [LOG] 找到 {len(preview_files)} 个可预览文件。")
    else: print(f"      [LOG] 未找到可用的预览文件。")

    update_task_status(task_id, 'READY', preview_files=preview_files)
    response_data = {'task_id': task_id, 'preview_files': preview_files}
    
    print(f"[TASK {task_id}] 5. 准备阶段完成，返回给前端。")
    return jsonify(response_data)


@app.route('/start_conversion', methods=['POST'])
def start_conversion():
    data = request.get_json()
    task_id, style_options = data.get('task_id'), data.get('style_options', {})
    print(f"\n[TASK {task_id}] ==> 收到开始转换信号。")
    if not task_id or task_id not in TASKS: return jsonify({'error': '无效的任务ID'}), 404
    update_task_status(task_id, 'QUEUED', progress=0, log="已加入转换队列")
    threading.Thread(target=run_conversion_thread, args=(task_id, style_options)).start()
    return jsonify({'task_id': task_id, 'message': '转换已开始'})

@app.route('/preview', methods=['POST'])
def preview_pdf():
    import pypandoc
    import weasyprint

    data = request.get_json()
    task_id, style_options = data.get('task_id'), data.get('style_options', {})
    preview_file_rel = data.get('preview_file')
    print(f"\n[TASK {task_id}] ==> 收到预览请求，目标文件: {preview_file_rel}")
    
    try:
        if not preview_file_rel: raise ValueError("请求中未指定要预览的文件名。")

        with TASKS_LOCK:
            task = TASKS.get(task_id, {})
            task_dir = task.get('task_dir')
        if not task_dir: return Response("任务无效", status=404, mimetype='text/plain')

        source_dir = os.path.join(task_dir, 'source')
        preview_file_abs = os.path.join(source_dir, os.path.normpath(preview_file_rel))
        
        if not os.path.abspath(preview_file_abs).startswith(os.path.abspath(source_dir)):
            print(f"[TASK {task_id}] 严重错误: 检测到路径穿越尝试！请求文件: {preview_file_rel}")
            return Response("非法的预览文件请求", status=403, mimetype='text/plain')

        print(f"[TASK {task_id}] 正在为文件生成预览: {preview_file_abs}")
        md_content = read_file_with_fallback(preview_file_abs)

        processed_md = preprocess_markdown_images(md_content, os.path.dirname(preview_file_abs))
        html_body = pypandoc.convert_text(source=processed_md, to='html', format='markdown+latex_macros', extra_args=[f'--highlight-style={style_options.get("code_theme", "kate")}'])
        full_html = f'<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body><article class="markdown-body">{html_body}</article></body></html>'
        css = weasyprint.CSS(string=get_css_style(style_options))
        pdf_bytes = weasyprint.HTML(string=full_html).write_pdf(stylesheets=[css])
        print(f"[TASK {task_id}] ==> 预览生成成功。")
        return Response(pdf_bytes, mimetype='application/pdf')
    except Exception as e:
        print(f"[TASK {task_id}] 错误：预览生成时发生异常！")
        traceback.print_exc()
        return Response(f"预览生成时发生错误: {e}", status=500, mimetype='text/plain')

@app.route('/status/<task_id>')
def task_status(task_id):
    logs = get_and_clear_logs(task_id)
    with TASKS_LOCK: task = TASKS.get(task_id, {})
    return jsonify({'state': task.get('state', 'UNKNOWN'), 'progress': task.get('progress', 0), 'logs': logs, 'error': task.get('error'), 'result_url': task.get('result_url')})

@app.route('/download/<task_id>')
def download_result(task_id):
    with TASKS_LOCK: task_info = TASKS.get(task_id)
    if not task_info or task_info.get('state') != 'SUCCESS': return "任务未完成或未找到", 404
    task_dir = task_info.get('task_dir')
    zip_filename = f"转换结果_{task_id[:8]}.zip"
    return send_from_directory(task_dir, zip_filename, as_attachment=True)

def check_dependencies():
    """检查Pandoc等外部依赖是否存在"""
    print("="*20 + " 正在进行启动环境自检 " + "="*20)
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        print("[自检 ✔] Pandoc 已找到。")
        return True
    except OSError:
        print("[自检 ❌] 错误：未在您的系统中找到Pandoc！")
        print("          pypandoc需要系统预先安装Pandoc才能工作。")
        print("          请前往 https://pandoc.org/installing.html 下载并安装。")
        print("          安装后请确保pandoc的可执行文件路径已添加到系统的PATH环境变量中。")
        print("="*70)
        if sys.platform.startswith('win'):
            print("          提示: 在Windows上，安装或修改PATH后，您可能需要重启您的命令行终端或IDE。")
        return False

if __name__ == '__main__':
    if check_dependencies():
        print("="*60)
        print("【v13 个性化增强版】一体化文件转换器 已启动")
        print("功能: 修复所有已知Bug, 大幅增强样式自定义能力。")
        print(f"所有输出文件将保存在: {OUTPUT_DIR}")
        print("请通过浏览器访问: http://127.0.0.1:5000")
        print("="*60)
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    else:
        print("\n依赖检查未通过，服务无法启动。请根据以上提示解决问题后重试。")
