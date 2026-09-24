async page => {
  await page.setViewportSize({ width: 1024, height: 1024 });
  await page.goto("file:///C:/Users/李星历/Desktop/token%20统计/token-monitor/tools/icon-preview.html");
  await page.screenshot({
    path: "output/playwright/icon-1024.png",
    type: "png",
    omitBackground: true,
  });
}
