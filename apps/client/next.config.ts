import type { NextConfig } from 'next';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const clientRoot = dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: 'standalone',
  turbopack: {
    root: clientRoot,
  },

  async headers() {
    return [
      // 1. 공유 페이지: 기존 제품 계약 유지
      {
        source: '/shared/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: 'frame-ancestors http: https: file: data:',
          },
        ],
      },
      // 2. 나머지 페이지: 임베딩 및 공유 페이지를 '제외한' 모든 경로
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
    // 환경변수로 백엔드 URL 설정 (기본값: 로컬 Gateway 직접 실행)
    const backendUrl = process.env.API_URL || 'http://localhost:8000';

    return [
      {
        source: '/api/:path*',
        // 공식 로컬 개발: Gateway 직접 실행(http://localhost:8000)
        // Docker nginx 경유: API_URL=http://localhost 주입
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
