/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
      {
        source: '/vmap/:path*',
        destination: 'http://localhost:8000/vmap/:path*',
      },
      {
        source: '/vmap',
        destination: 'http://localhost:8000/vmap',
      },
      {
        source: '/vast',
        destination: 'http://localhost:8000/vast',
      },
      {
        source: '/vast/:path*',
        destination: 'http://localhost:8000/vast/:path*',
      },
      {
        source: '/static/:path*',
        destination: 'http://localhost:8000/static/:path*',
      },
    ];
  },
};

export default nextConfig;
