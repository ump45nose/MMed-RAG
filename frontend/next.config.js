/** @type {import('next').NextConfig} */
module.exports = {
  output: "standalone",
  async rewrites() {
    // 本地宿主机开发时，把前端相对 API 请求代理到 FastAPI 后端。
    if (!process.env.NEXT_API_PROXY_TARGET) {
      return [];
    }

    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_API_PROXY_TARGET}/api/:path*`,
      },
    ];
  },
  experimental: {
    // This is needed for standalone output to work correctly
    outputFileTracingRoot: undefined,
    outputStandalone: true,
    skipMiddlewareUrlNormalize: true,
    skipTrailingSlashRedirect: true,
  },
};
