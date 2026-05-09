import { createContext, useContext, ReactNode } from "react";

export interface MockUser {
  user_id: string;
  username: string;
  nickname: string;
  avatar: string;
}

export interface MockAuthState {
  user: MockUser;
  loading: boolean;
  setUser: (user: MockUser | null) => void;
  isMock: true;
}

const mockUser: MockUser = {
  user_id: "mock-user-001",
  username: "admin",
  nickname: "管理员",
  avatar: "https://api.dicebear.com/7.x/initials/svg?seed=Admin&backgroundColor=3b82f6&fontFamily=Arial&fontSize=38&textColor=ffffff",
};

const MockAuthContext = createContext<MockAuthState>({
  user: mockUser,
  loading: false,
  setUser: () => {},
  isMock: true,
});

export function MockAuthProvider({ children }: { children: ReactNode }) {
  return (
    <MockAuthContext.Provider value={{ user: mockUser, loading: false, setUser: () => {}, isMock: true }}>
      {children}
    </MockAuthContext.Provider>
  );
}

export function useMockAuth() {
  return useContext(MockAuthContext);
}