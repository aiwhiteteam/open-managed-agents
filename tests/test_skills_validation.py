from tests.conftest import TEST_HEADERS


async def test_skill_upload_rejects_missing_description(client):
    response = await client.post(
        "/v1/skills",
        headers=TEST_HEADERS,
        files={"files": ("skill/SKILL.md", b"---\nname: research\n---\nBody.", "text/markdown")},
    )

    assert response.status_code == 422
    assert "description" in response.json()["error"]["message"]


async def test_skill_upload_rejects_mixed_top_level_directories(client):
    response = await client.post(
        "/v1/skills",
        headers=TEST_HEADERS,
        files=[
            (
                "files",
                (
                    "skill/SKILL.md",
                    b"---\nname: research\ndescription: Use sources.\n---\nBody.",
                    "text/markdown",
                ),
            ),
            ("files", ("other/schema.json", b"{}", "application/json")),
        ],
    )

    assert response.status_code == 422
    assert "top-level" in response.json()["error"]["message"]


async def test_skill_upload_persists_manifest_metadata(client):
    response = await client.post(
        "/v1/skills",
        headers=TEST_HEADERS,
        files={
            "files": (
                "skill/SKILL.md",
                b"---\nname: research\ndescription: Use sources.\n---\nBody.",
                "text/markdown",
            )
        },
    )

    assert response.status_code == 201, response.text
    skill = response.json()
    assert skill["name"] == "research"
    assert skill["description"] == "Use sources."
    assert skill["top_level_directory"] == "skill"
    assert skill["version"]["manifest"]["name"] == "research"
