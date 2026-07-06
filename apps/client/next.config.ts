import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',

  async headers() {
    return [
      // 1. 임베딩 페이지: 어디서든 허용
      {
        source: '/embed/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: 'frame-ancestors http: https: file: data:',
          },
        ],
      },
      // 2. 공유 페이지: 어디서든 허용
      {
        source: '/shared/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: 'frame-ancestors http: https: file: data:',
          },
        ],
      },
      // 3. [수정됨] 나머지 페이지: 임베딩 및 공유 페이지를 '제외한' 모든 경로
      // 정규식 설명: (?!embed|shared) -> embed나 shared로 시작하지 않는 모든 경로
      {
        source: '/((?!embed|shared).*)',
        headers: [
          {
            key: 'X-Frame-Options',
            value: 'SAMEORIGIN',
          },
          {
            key: 'Content-Security-Policy',
            value: "frame-ancestors 'self'",
          },
        ],
      },
    ];
  },
  async rewrites() {
    // 환경변수로 백엔드 URL 설정 (기본값: Docker nginx 경유 로컬 API)
    const backendUrl = process.env.API_URL || 'http://localhost';

    return [
      {
        source: '/api/:path*',
        // 로컬 Docker 개발: localhost
        // Gateway 직접 실행: .env.local에 API_URL=http://localhost:8000 설정
        // 배포 테스트: .env.local에 API_URL 설정
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
  experimental: {
    serverActions: {
      bodySizeLimit: '50mb', //파일 업로드 제한 50mb
    },
    // Proxy client body size limit for large file uploads.
    proxyClientMaxBodySize: '50mb',
    // [ADD] Proxy Timeout 설정 (2분) - LlamaParse/OCR 등 긴 요청 대비
    proxyTimeout: 120000,
  },
};

export default nextConfig;
