import type { Role } from "@/types/api";

/**
 * 本地身份切换器使用的最小配置。
 *
 * 页面直接显示数据库中的业务账号，例如 P1001、T1001，避免页面自造短编号
 * 与真实身份产生对应歧义。身份类型仍使用中文前缀，便于人工测试时快速区分。
 */
export interface DemoIdentity {
  userId: string;
  role: Role;
  label: string;
}

export interface DemoIdentityGroup {
  key: "parent" | "teacher" | "advisor";
  label: string;
  identities: readonly DemoIdentity[];
}

/** 本地模式共提供三个家长、两个授课教师和两个销售顾问老师。 */
export const demoIdentityGroups: readonly DemoIdentityGroup[] = [
  {
    key: "parent",
    label: "家长",
    identities: [
      { userId: "P1001", role: "parent", label: "家长P1001" },
      { userId: "P1002", role: "parent", label: "家长P1002" },
      { userId: "P1003", role: "parent", label: "家长P1003" },
    ],
  },
  {
    key: "teacher",
    label: "授课教师",
    identities: [
      { userId: "T1001", role: "teacher", label: "教师T1001" },
      { userId: "T1002", role: "teacher", label: "教师T1002" },
    ],
  },
  {
    key: "advisor",
    label: "销售顾问",
    identities: [
      { userId: "T1004", role: "teacher", label: "销售顾问T1004" },
      { userId: "T1006", role: "teacher", label: "销售顾问T1006" },
    ],
  },
];

/** 扁平列表供身份查找和测试使用，分组信息只负责页面展示。 */
export const demoIdentities: readonly DemoIdentity[] = demoIdentityGroups.flatMap(
  (group) => group.identities,
);

export function findDemoIdentity(userId: string | null | undefined): DemoIdentity | undefined {
  return demoIdentities.find((identity) => identity.userId === userId);
}
