/* 1. 设置全局的新底色和文字颜色 */
:root, html, body {
    /* 【在此处修改你想要的替代背景色】 */
    background-color: #121212 !important; 
    /* 【在此处修改文字颜色，确保能看清】 */
    color: #e0e0e0 !important;
    /* 确保高度占满，否则可能出现半截白 */
    min-height: 100vh !important;
}

/* 2. 核弹级通用选择器：抹除一切 */
*, *::before, *::after {
    /* 强制所有元素背景透明，让它们透出上面的 body 底色 */
    background-color: transparent !important;
    background-image: none !important; /* 移除可能的背景图纹理 */
    
    /* 彻底杀死磨砂玻璃效果 */
    -webkit-backdrop-filter: none !important;
    backdrop-filter: none !important;
    
    /* 移除阴影和发光，这些通常也是白色的 */
    box-shadow: none !important;
    text-shadow: none !important;
    
    /* 强制边框颜色变暗，避免白色刺眼边框 */
    border-color: #333 !important;
    
    /* 强制文字颜色继承 body 的设置 */
    color: inherit !important;
}

/* 3. 例外处理：交互元素必须有背景才能被看见 */
/* 强制给输入框、按钮、选择器加上深色背景 */
input, textarea, select, button, [role="button"] {
    background-color: #2a2a2a !important;
    border: 1px solid #555 !important;
    color: #fff !important;
}

/* 4. 图片和视频的处理 */
/* 确保媒体元素本身不透明，但移除它们上面可能覆盖的滤镜 */
img, video, svg, canvas {
    opacity: 1 !important;
    filter: none !important;
}

/* 5. 处理特殊的链接颜色，确保可读 */
a, a:hover, a:visited {
    color: #4dabf7 !important; /* 设置一个显眼的链接色 */
    text-decoration: underline !important;
}
