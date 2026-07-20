"""Group & topic management: list/create/select groups, list/create topics."""
from app import config


class GroupsMixin:
    async def list_groups(self):
        """Groups/supergroups where the user is the creator or an admin."""
        out = []
        async for d in self.client.iter_dialogs():
            ent = d.entity
            is_group = getattr(d, "is_group", False)
            is_channel = getattr(d, "is_channel", False)
            megagroup = getattr(ent, "megagroup", False)
            if not (is_group or (is_channel and megagroup)):
                continue
            # Only groups the user owns or administers.
            is_creator = bool(getattr(ent, "creator", False))
            is_admin = getattr(ent, "admin_rights", None) is not None
            if not (is_creator or is_admin):
                continue
            out.append(
                {
                    "id": d.id,
                    "title": d.name,
                    "is_forum": bool(getattr(ent, "forum", False)),
                    "role": "owner" if is_creator else "admin",
                }
            )
        return out

    async def create_group(self, title: str, enable_topics: bool = True):
        """Create a supergroup and (optionally) enable Topics/forum mode."""
        from telethon.tl import functions

        res = await self.client(
            functions.channels.CreateChannelRequest(
                title=title, about="Created by Telegram Uploader", megagroup=True
            )
        )
        channel = res.chats[0]
        peer_id = int(f"-100{channel.id}")
        if enable_topics:
            try:
                await self.client(
                    functions.channels.ToggleForumRequest(channel=channel, enabled=True)
                )
            except Exception as e:
                self.log(f"⚠️ Could not enable Topics: {e}")
        self.select_group(peer_id)
        self.log(f"✅ Created group '{title}' ({peer_id}).")
        return {"id": peer_id, "title": title}

    def select_group(self, group_id: int):
        cfg = config.read_config()
        cfg["group_id"] = int(group_id)
        config.write_config(cfg)
        self.emit("group", {"group_id": int(group_id)})
        return {"group_id": int(group_id)}

    async def _resolve_entity(self, group_id: int):
        """Resolve a group entity robustly (falls back to scanning dialogs)."""
        gid = int(group_id)
        try:
            return await self.client.get_entity(gid)
        except Exception:
            async for d in self.client.iter_dialogs():
                if d.id == gid:
                    return d.entity
            raise ValueError("Group not found or not accessible.")

    async def list_topics(self, group_id: int):
        from telethon.tl import functions

        entity = await self._resolve_entity(group_id)
        if not getattr(entity, "forum", False):
            return {"is_forum": False, "topics": []}
        res = await self.client(
            functions.channels.GetForumTopicsRequest(
                channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
            )
        )
        topics = []
        for t in res.topics:
            # Skip deleted-topic markers; keep real topics.
            if hasattr(t, "title") and hasattr(t, "id"):
                topics.append({"id": t.id, "title": t.title})
        return {"is_forum": True, "topics": topics}

    async def create_topic(self, group_id: int, title: str):
        from telethon.tl import functions

        entity = await self._resolve_entity(group_id)
        if not getattr(entity, "forum", False):
            # Enable Topics automatically so the created topic works.
            try:
                await self.client(
                    functions.channels.ToggleForumRequest(channel=entity, enabled=True)
                )
                entity = await self._resolve_entity(group_id)
            except Exception as e:
                raise ValueError(f"Group has no Topics and enabling failed: {e}")
        res = await self.client(
            functions.channels.CreateForumTopicRequest(channel=entity, title=title)
        )
        # A forum topic's id == the id of the service message that opened it,
        # delivered inside an UpdateNewChannelMessage.
        topic_id = None
        for u in getattr(res, "updates", []):
            msg = getattr(u, "message", None)
            if msg is not None and hasattr(msg, "id"):
                topic_id = msg.id
                break
        if topic_id is None:  # fallback for other update shapes
            for u in getattr(res, "updates", []):
                if getattr(u, "id", None) is not None:
                    topic_id = u.id
                    break
        self.log(f"✅ Created topic '{title}' (id={topic_id}).")
        return {"id": topic_id, "title": title}

    async def create_topics_for_folders(self, group_id: int, folder_names: list[str],
                                        max_topics: int = 30):
        """Auto-create one topic per folder name; return {name: topic_id}.

        Reuses existing topics with the same title. Caps at max_topics.
        """
        existing = {}
        info = await self.list_topics(group_id)
        for t in info.get("topics", []):
            existing[t["title"].lower()] = t["id"]
        mapping = {}
        created = 0
        capped = False
        for raw in folder_names:
            name = "General" if raw in (".", "", None) else raw
            key = name.lower()
            if key in existing:
                mapping[raw] = existing[key]
                continue
            if created >= max_topics:
                capped = True
                continue
            made = await self.create_topic(group_id, name[:128])
            if made.get("id"):
                mapping[raw] = made["id"]
                existing[key] = made["id"]
                created += 1
        return {"mapping": mapping, "created": created, "capped": capped,
                "max_topics": max_topics}
