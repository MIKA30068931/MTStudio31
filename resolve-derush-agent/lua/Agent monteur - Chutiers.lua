-- Agent monteur - Chutiers
-- Prépare les chutiers (rushs classés, musiques et SFX) avant de monter.
-- Ce script lance l'agent dans une fenêtre noire. L'agent te demande ensuite le dossier de montage.
-- Installation : copie ce fichier dans le dossier Scripts/Utility de DaVinci Resolve, puis redémarre Resolve.
-- Si ton agent n'est pas dans C:\agent, change la ligne ci-dessous.
local agent = "C:\\agent\\derush_agent.py"

local commande = 'start "Agent monteur" cmd /k py -3 "' .. agent .. '" --chutiers'
os.execute(commande)
