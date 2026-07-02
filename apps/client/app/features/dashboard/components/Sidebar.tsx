'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import { authApi } from '../../auth/api/authApi';
import {
  Search,
  Settings,
  BookOpen,
  BarChart3,
  Puzzle,
  Home,
  LogOut,
  Menu,
  Building2,
  LayoutDashboard,
  ShieldCheck,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  ACTIVE_ORGANIZATION_CHANGED_EVENT,
  getStoredActiveOrganizationId,
} from '@/lib/activeOrganization';
import { apiClient } from '@/lib/apiClient';

const navigationItems = [
  {
    name: '홈',
    href: '/dashboard',
    icon: Home,
  },
  {
    name: '내 모듈',
    href: '/dashboard/mymodule',
    icon: Puzzle,
  },
  {
    name: '마켓플레이스',
    href: '/dashboard/explore',
    icon: Search,
  },
  {
    name: '통계',
    href: '/dashboard/statistics',
    icon: BarChart3,
  },
  {
    name: '지식 관리',
    href: '/dashboard/knowledge',
    icon: BookOpen,
  },
  {
    name: '관리',
    href: '/dashboard/admin',
    icon: ShieldCheck,
    managerOnly: true,
  },
  {
    name: '설정',
    href: '/dashboard/settings',
    icon: Settings,
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [userName, setUserName] = useState('사용자');
  const [userEmail, setUserEmail] = useState('');
  const [organizationName, setOrganizationName] = useState('');
  const [isOrganizationManager, setIsOrganizationManager] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Fetch user info
  useEffect(() => {
    const fetchUserInfo = async () => {
      try {
        const userInfo = await authApi.me();
        if (userInfo.user?.name) {
          setUserName(userInfo.user.name);
        }
        if (userInfo.user?.email) {
          setUserEmail(userInfo.user.email);
        }
      } catch {
        // Silent error handling
      }
    };

    fetchUserInfo();
  }, []);

  useEffect(() => {
    const fetchOrganization = async () => {
      try {
        const organizationId = getStoredActiveOrganizationId();
        if (!organizationId) {
          setOrganizationName('');
          setIsOrganizationManager(false);
          return;
        }

        const response = await apiClient.get('/organizations/current');
        if (response.data?.name) {
          setOrganizationName(response.data.name);
        }
        setIsOrganizationManager(response.data?.is_manager === true);
      } catch {
        setOrganizationName('');
        setIsOrganizationManager(false);
      }
    };

    fetchOrganization();
    window.addEventListener(ACTIVE_ORGANIZATION_CHANGED_EVENT, fetchOrganization);
    return () =>
      window.removeEventListener(
        ACTIVE_ORGANIZATION_CHANGED_EVENT,
        fetchOrganization,
      );
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // Silent error handling
    } finally {
      localStorage.removeItem('access_token');
      router.push('/auth/login');
    }
  };

  return (
    <aside
      className={cn(
        'relative flex h-full flex-col justify-between border-r border-slate-200 bg-white px-4 py-5 transition-all duration-300',
        isCollapsed ? 'w-[80px]' : 'w-[248px]',
      )}
    >
      {/* Toggle Button */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className={cn(
          'absolute z-50 rounded-md p-1.5 text-slate-500 transition-all duration-300 hover:bg-slate-100 hover:text-slate-900',
          isCollapsed ? 'left-1/2 top-6 -translate-x-1/2' : 'right-4 top-5',
        )}
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Logo */}
      {isCollapsed ? (
        <button
          onClick={() => router.push('/dashboard')}
          className="mt-12 grid h-10 w-10 place-items-center rounded-lg bg-slate-950 text-white transition-colors hover:bg-slate-800"
          aria-label="대시보드 홈"
        >
          <LayoutDashboard size={20} />
        </button>
      ) : (
        <div className="mb-7 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-slate-950 text-white">
            <LayoutDashboard size={20} />
          </div>
          <div className="min-w-0">
            <button
              onClick={() => router.push('/dashboard')}
              className="block text-left text-sm font-black text-slate-950"
            >
              Nodease
            </button>
            <span className="block truncate text-xs font-semibold text-slate-500">
              AI workflow control
            </span>
          </div>
        </div>
      )}

      {/* Main Navigation */}
      <nav className="flex-1 space-y-1">
        {navigationItems
          .filter((item) => !item.managerOnly || isOrganizationManager)
          .map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== '/dashboard' && pathname.startsWith(`${item.href}/`));
          const Icon = item.icon;

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg py-2.5 text-sm font-semibold transition-colors',
                isCollapsed ? 'justify-center px-2' : 'px-3',
                isActive
                  ? 'bg-slate-950 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!isCollapsed && <span>{item.name}</span>}
            </Link>
          );
        })}
      </nav>

      {!isCollapsed && organizationName && (
        <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <Building2 className="h-3.5 w-3.5 text-blue-600" />
            <span className="truncate">{organizationName}</span>
          </div>
        </div>
      )}

      {/* User Info Footer */}
      <div
        className={cn(
          'relative border-t border-slate-200 pt-4 transition-all',
          isCollapsed && 'items-center justify-center',
        )}
        ref={dropdownRef}
      >
        <button
          onClick={() => setIsDropdownOpen(!isDropdownOpen)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg text-left transition-colors hover:bg-slate-50',
            isCollapsed ? 'justify-center p-0' : 'p-2',
          )}
        >
          <div className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-full bg-slate-200 text-xs font-black text-slate-700">
            {userName.charAt(0).toUpperCase()}
          </div>
          {!isCollapsed && (
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-black text-slate-900">
                {userName}
              </p>
              <p className="truncate text-xs font-semibold text-slate-500">
                {userEmail || '사용자'}
              </p>
            </div>
          )}
        </button>

        {/* Dropdown Menu (Upwards) */}
        {isDropdownOpen && (
          <div
            className={cn(
              'absolute bottom-full mb-2 w-full z-50',
              isCollapsed ? 'left-10 w-48' : 'left-0 px-2',
            )}
          >
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span>로그아웃</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
