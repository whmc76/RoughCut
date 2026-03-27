from roughcut.avatar.materials import detect_avatar_material_library_warnings


def test_detect_avatar_material_library_warnings_flags_demo_profiles():
    warnings = detect_avatar_material_library_warnings(
        [
            {
                "display_name": "演示创作者A",
                "presenter_alias": "CreatorDemoA",
                "creator_profile": {
                    "identity": {"public_name": "CreatorDemoA", "title": None, "bio": None},
                    "positioning": {
                        "creator_focus": None,
                        "expertise": [],
                        "audience": None,
                        "style": None,
                        "tone_keywords": [],
                    },
                    "publishing": {
                        "primary_platform": None,
                        "active_platforms": [],
                        "signature": None,
                    },
                    "business": {"contact": None, "collaboration_notes": None},
                    "archive_notes": None,
                },
                "profile_dashboard": {"completeness_score": 20},
            }
        ]
    )

    assert warnings
    assert "演示创作者A" in warnings[0]
    assert "profiles.json" in warnings[0]


def test_detect_avatar_material_library_warnings_ignores_real_profiles():
    warnings = detect_avatar_material_library_warnings(
        [
            {
                "display_name": "赛博迪克朗",
                "presenter_alias": "CyberDickLang",
                "creator_profile": {
                    "identity": {"public_name": "赛博迪克朗", "title": "EDC评测作者", "bio": "长期做开箱和测评。"},
                    "positioning": {
                        "creator_focus": "EDC装备",
                        "expertise": ["手电", "工具"],
                        "audience": "装备爱好者",
                        "style": "克制直接",
                        "tone_keywords": ["真实"],
                    },
                    "publishing": {
                        "primary_platform": "B站",
                        "active_platforms": ["B站", "小红书"],
                        "signature": "只讲真实体验",
                    },
                    "business": {"contact": "test@example.com", "collaboration_notes": "可接商单"},
                    "archive_notes": "真实创作者档案",
                },
                "profile_dashboard": {"completeness_score": 100},
            }
        ]
    )

    assert warnings == []
