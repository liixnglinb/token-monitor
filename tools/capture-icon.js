async page => {
  await page.setViewportSize({ width: 1024, height: 1024 });
  // 用 __dirname 相对定位，避免写死本机绝对路径（公开仓库不应含用户名）
  const path = require("node:path");
  const { pathToFileURL } = require("node:url");
  await page.goto(pathToFileURL(path.join(__dirname, "icon-preview.html")).href);
  await page.screenshot({
    path: "output/playwright/icon-1024.png",
    type: "png",
    omitBackground: true,
  });
}
