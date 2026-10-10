"""浏览器指纹与自动化痕迹清理。

在页面任何脚本执行之前注入（add_init_script），覆盖：
  - navigator.webdriver
  - 各种 navigator 属性（会被 headless 特征检测读取）
  - WebGL vendor / renderer
  - permissions.query 的 notifications 分支
  - chrome.* 对象可枚举性
  - iframe.contentWindow 泄漏
  - Function.prototype.toString 伪装，避免"被 patch 过的函数"被识别
"""

STEALTH_JS = r"""
(() => {
  if (window.__lcs_stealth__) return;
  window.__lcs_stealth__ = true;

  const patched = new WeakSet();
  const nativeToString = Function.prototype.toString;
  const fakeToString = function () {
    if (patched.has(this)) return 'function () { [native code] }';
    return nativeToString.call(this);
  };
  const mark = (fn) => { try { patched.add(fn); } catch (e) {} return fn; };
  try {
    Object.defineProperty(fakeToString, 'toString', { value: nativeToString, configurable: true });
    Function.prototype.toString = mark(fakeToString);
  } catch (e) {}

  const def = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, { get: () => value, configurable: true });
    } catch (e) {}
  };

  def(navigator, 'webdriver', undefined);
  def(navigator, 'platform', 'Win32');
  def(navigator, 'vendor', 'Google Inc.');
  def(navigator, 'productSub', '20030107');
  def(navigator, 'hardwareConcurrency', 8);
  def(navigator, 'deviceMemory', 8);
  def(navigator, 'maxTouchPoints', 0);
  def(navigator, 'doNotTrack', null);
  def(navigator, 'language', 'zh-CN');
  def(navigator, 'languages', Object.freeze(['zh-CN', 'zh', 'en-US', 'en']));

  // navigator.plugins / mimeTypes：headless 里是空的，这里补齐长度和 item()
  const pluginNames = [
    { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
    { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
    { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
    { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer' },
    { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer' },
  ];
  const plugins = pluginNames.map((p) => ({
    name: p.name,
    filename: p.filename,
    description: 'Portable Document Format',
    length: 1,
    item: () => null,
    namedItem: () => null,
  }));
  plugins.item = (i) => plugins[i] || null;
  plugins.namedItem = (n) => plugins.find((p) => p.name === n) || null;
  plugins.refresh = () => {};
  def(navigator, 'plugins', plugins);
  def(navigator, 'mimeTypes', Object.freeze([]));

  // chrome 对象：真实 Chrome/Edge 一定有 runtime / app / csi / loadTimes
  if (!window.chrome) window.chrome = {};
  const chromeStub = window.chrome;
  try {
    if (!chromeStub.runtime) {
      Object.defineProperty(chromeStub, 'runtime', {
        value: {
          id: undefined,
          connect: () => ({ onMessage: { addListener: () => {}, removeListener: () => {} },
                            postMessage: () => {}, disconnect: () => {} }),
          sendMessage: () => {},
          onMessage: { addListener: () => {}, removeListener: () => {} },
        },
        configurable: true,
        writable: true,
      });
    }
    if (!chromeStub.app) {
      Object.defineProperty(chromeStub, 'app', {
        value: { isInstalled: false, InstallState: { DISABLED: 'disabled' },
                 RunningState: { CANNOT_RUN: 'cannot_run' } },
        configurable: true, writable: true,
      });
    }
    if (!chromeStub.csi) {
      Object.defineProperty(chromeStub, 'csi', {
        value: () => ({ onloadT: Date.now(), startE: Date.now() - 1200, pageT: 1200, tran: 15 }),
        configurable: true, writable: true,
      });
    }
    if (!chromeStub.loadTimes) {
      Object.defineProperty(chromeStub, 'loadTimes', {
        value: () => ({ requestTime: Date.now() / 1000 - 1, startLoadTime: Date.now() / 1000 - 1,
                        commitLoadTime: Date.now() / 1000 - 0.8,
                        finishDocumentLoadTime: Date.now() / 1000 - 0.4,
                        finishLoadTime: Date.now() / 1000 - 0.3,
                        firstPaintTime: Date.now() / 1000 - 0.2,
                        firstPaintAfterLoadTime: 0, navigationType: 'Other',
                        wasFetchedViaSpdy: true, wasNpnNegotiated: true,
                        npnNegotiatedProtocol: 'h2', wasAlternateProtocolAvailable: false,
                        connectionInfo: 'h2' }),
        configurable: true, writable: true,
      });
    }
  } catch (e) {}

  // permissions.query：headless 会在 notifications 上暴露 Notification 的 permission 状态
  try {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    const newQuery = function (params) {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: (window.Notification && Notification.permission) || 'default',
                                 onchange: null });
      }
      return origQuery(params);
    };
    navigator.permissions.query = mark(newQuery);
  } catch (e) {}

  // WebGL 指纹
  try {
    const GPU = { 37445: 'Intel Inc.', 37446: 'Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0' };
    const patch = (proto) => {
      if (!proto || !proto.getParameter) return;
      const orig = proto.getParameter;
      proto.getParameter = mark(function (p) {
        if (Object.prototype.hasOwnProperty.call(GPU, p)) return GPU[p];
        return orig.apply(this, arguments);
      });
    };
    patch(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
    patch(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  } catch (e) {}

  // 屏幕 / 时区细节
  try {
    if (screen.availWidth && !screen.availHeight) {
      Object.defineProperty(screen, 'availHeight', { get: () => screen.height, configurable: true });
    }
  } catch (e) {}

  // 清理 Playwright 可能留下的全局标记
  try {
    delete window.__playwright__binding__;
    delete window.__pw_manual;
    delete window.__PW_inspect;
  } catch (e) {}

  // iframe.contentWindow 一致性
  try {
    const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    if (desc && desc.get) {
      Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: mark(function () { return desc.get.call(this); }),
        configurable: true,
      });
    }
  } catch (e) {}
})();
"""


ANTI_THROTTLE_ARGS = [
    # 后台标签页 / 遮挡窗口不要降频，否则心跳被拉长，风控直接判定异常
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--disable-hang-monitor",
    "--disable-popup-blocking",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter,OptimizationHints",
]


IGNORE_DEFAULT_ARGS = ["--enable-automation", "--enable-blink-features=IdleDetection"]
