"use client";

import { Box, Button, Typography } from "@mui/material";
import type { DocumentData } from "@/lib/types/kb";

export default function DocumentLineItem({ 
	documentData, 
	onDelete 
}: { 
	documentData: DocumentData
	onDelete: (documentData: DocumentData) => void | Promise<void>
}) {

	// Pass deletion event to parent (DocumentDisplay)
	async function handleDelete() {
		await onDelete(documentData) 
	}

	return (
			<Box
				sx={{
					display: "flex",
				alignItems: "center",
				justifyContent: "space-between",
				gap: 2,
				p: 1.5,
				border: "1px solid",
				borderColor: "divider",
				borderRadius: 1.5,
			}}
		>
			<Box sx={{ minWidth: 0 }}>
				<Typography fontWeight={600} noWrap>
					{documentData.fileName}
				</Typography>
				<Typography variant="body2" color="text.secondary">
					{documentData.uploadedAt}
				</Typography>
			</Box>

			<Button 
				variant="text"
				onClick={handleDelete}
				size="small" 
				color="error" 
			>
				Delete
			</Button>
		</Box>
    )
}
