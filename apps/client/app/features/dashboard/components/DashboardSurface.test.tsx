import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DashboardPageHeader } from './DashboardSurface';

describe('DashboardPageHeader', () => {
  it('페이지 제목을 장식 아이콘 없이 표시한다', () => {
    const { container } = render(
      <DashboardPageHeader
        title="워크플로우"
        description="워크플로우 운영 상태를 확인합니다."
      />,
    );

    expect(
      screen.getByRole('heading', { level: 1, name: '워크플로우' }),
    ).toHaveClass('text-2xl');
    expect(container.querySelector('header svg')).not.toBeInTheDocument();
  });
});
